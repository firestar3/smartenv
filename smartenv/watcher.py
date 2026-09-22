"""Optional watchdog integration for reloading file-backed configuration."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from time import monotonic
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional, Sequence

if TYPE_CHECKING:
    from smartenv.core import Env

__all__ = ["FileWatcher"]


class FileWatcher:
    """Watch configuration files and reload their owning Env instance.

    Args:
        env_instance: Configuration instance to reload atomically.
        file_paths: Files to watch; each parent directory is watched once.
        on_reload: Additional callback after a successful reload. Env's own
            callback is already invoked by its reload method.

    Events for the same file within 0.5 seconds are ignored. Reload or callback
    failures are recorded in ``env_instance.warnings`` and do not kill the
    observer, allowing a subsequent edit to recover.
    """

    def __init__(
        self,
        env_instance: Env,
        file_paths: Sequence[str],
        on_reload: Optional[Callable[[Env], None]] = None,
    ) -> None:
        self._env = env_instance
        self._paths = frozenset(_normalize_path(path) for path in file_paths)
        self._on_reload = on_reload
        self._lock = threading.RLock()
        self._last_events: Dict[str, float] = {}
        self._observer: Optional[Any] = None

    def start(self) -> None:
        """Start a daemon observer, or do nothing when already started.

        Raises:
            ImportError: If watchdog is unavailable, with an installation hint.
            OSError: If a parent directory cannot be watched.
        """
        with self._lock:
            if self._observer is not None:
                return
            try:
                from watchdog.events import FileSystemEventHandler
                from watchdog.observers import Observer
            except ImportError as exc:
                raise ImportError(
                    "hot reload requires watchdog; install it with: pip install smartenv[watch]"
                ) from exc

            observer = Observer()
            observer.daemon = True
            handler = FileSystemEventHandler()
            # Creation and moves cover editors that save by replacing the file.
            for event_name in ("on_modified", "on_created", "on_moved", "on_deleted"):
                setattr(handler, event_name, self._handle_event)
            for directory in sorted({str(Path(path).parent) for path in self._paths}):
                observer.schedule(handler, directory, recursive=False)
            self._last_events.clear()
            self._observer = observer
            try:
                observer.start()
            except Exception:
                self._observer = None
                observer.stop()
                if observer.is_alive():
                    observer.join()
                raise

    def stop(self) -> None:
        """Stop the observer and wait for it, safely allowing repeated calls."""
        with self._lock:
            observer = self._observer
            self._observer = None
        if observer is not None:
            observer.stop()
            # A reload callback may close its own Env on the observer thread.
            if observer is not threading.current_thread():
                observer.join()

    def _handle_event(self, event: Any) -> None:
        """Reload for matching file events, suppressing duplicate notifications."""
        if event.is_directory:
            return
        event_paths = {
            _normalize_path(os.fsdecode(path))
            for path in (event.src_path, getattr(event, "dest_path", ""))
            if path
        }
        matched = event_paths.intersection(self._paths)
        if not matched:
            return
        with self._lock:
            if self._observer is None:
                return
            now = monotonic()
            changed = {
                path
                for path in matched
                if path not in self._last_events or now - self._last_events[path] >= 0.5
            }
            if not changed:
                return
            for path in changed:
                self._last_events[path] = now
        try:
            self._env.reload()
            if self._on_reload is not None:
                self._on_reload(self._env)
        except Exception as exc:
            self._env._add_warning(f"hot_reload failed: {exc}")


def _normalize_path(path: str) -> str:
    """Return an absolute path with platform-appropriate case normalization."""
    return os.path.normcase(str(Path(path).resolve()))
