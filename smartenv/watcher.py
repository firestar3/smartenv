"""Optional watchdog integration for reloading file-backed configuration."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from time import monotonic
from typing import TYPE_CHECKING, Any, Callable, Optional, Sequence

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

    Reloads run after 0.5 seconds without a matching event, so a burst of writes
    reads the completed save. A single daemon worker serializes reloads and
    callbacks. Reload or callback failures are recorded in
    ``env_instance.warnings``, allowing a subsequent edit to recover.
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
        self._condition = threading.Condition()
        self._deadline: Optional[float] = None
        self._active = False
        self._observer: Optional[Any] = None
        self._worker: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start daemon observation and reload threads.

        Repeated calls while running, and calls with no file paths, do nothing.

        Raises:
            ImportError: If watchdog is unavailable, with an installation hint.
            OSError: If a parent directory cannot be watched.
            RuntimeError: If a previous reload is still shutting down.
        """
        observer: Optional[Any] = None
        worker: Optional[threading.Thread] = None
        try:
            with self._condition:
                if self._active or not self._paths:
                    return
                if (
                    self._worker is not None
                    and self._worker.is_alive()
                    or self._observer is not None
                    and self._observer.is_alive()
                ):
                    raise RuntimeError("the previous file watcher is still stopping")
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
                # Creation and moves cover editors that replace the saved file.
                for event_name in ("on_modified", "on_created", "on_moved", "on_deleted"):
                    setattr(handler, event_name, self._handle_event)
                for directory in sorted({str(Path(path).parent) for path in self._paths}):
                    observer.schedule(handler, directory, recursive=False)
                worker = threading.Thread(target=self._run, name="smartenv-reload", daemon=True)
                self._deadline = None
                self._observer = observer
                self._worker = worker
                self._active = True
                observer.start()
                worker.start()
        except Exception:
            # Join outside the condition: an already-started observer may be
            # delivering an event which needs that same lock.
            if observer is not None:
                with self._condition:
                    self._active = False
                    self._deadline = None
                    self._condition.notify_all()
                observer_alive = observer.is_alive()
                observer.stop()
                if observer_alive:
                    observer.join()
                if worker is not None and worker.is_alive():
                    worker.join()
                with self._condition:
                    self._observer = None
                    self._worker = None
            raise

    def stop(self) -> None:
        """Cancel pending reloads and wait for observation and reloads to finish.

        Repeated calls are safe. When called inside a reload callback, the worker
        finishes that callback and exits without trying to join itself.
        """
        with self._condition:
            self._active = False
            self._deadline = None
            observer = self._observer
            worker = self._worker
            self._condition.notify_all()
        if observer is not None:
            observer.stop()
            if observer is not threading.current_thread():
                observer.join()
        if worker is not None and worker is not threading.current_thread():
            worker.join()

    def _run(self) -> None:
        """Consume the most recent deadline, then reload outside the state lock."""
        while True:
            with self._condition:
                while self._active:
                    if self._deadline is None:
                        self._condition.wait()
                        continue
                    remaining = self._deadline - monotonic()
                    if remaining > 0:
                        self._condition.wait(timeout=remaining)
                        continue
                    self._deadline = None
                    break
                if not self._active:
                    return
            try:
                self._env.reload()
                with self._condition:
                    active = self._active
                if active and self._on_reload is not None:
                    self._on_reload(self._env)
            except Exception as exc:
                self._env._add_warning(f"hot_reload failed: {exc}")

    def _handle_event(self, event: Any) -> None:
        """Extend the quiet period for each matching file event."""
        if event.is_directory:
            return
        event_paths = {
            _normalize_path(os.fsdecode(path))
            for path in (event.src_path, getattr(event, "dest_path", ""))
            if path
        }
        if not event_paths.intersection(self._paths):
            return
        with self._condition:
            if not self._active:
                return
            self._deadline = monotonic() + 0.5
            self._condition.notify_all()


def _normalize_path(path: str) -> str:
    """Return an absolute path with platform-appropriate case normalization."""
    return os.path.normcase(str(Path(path).resolve()))
