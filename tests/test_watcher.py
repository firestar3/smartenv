"""Watcher lifecycle and reload tests, including real filesystem delivery."""

from __future__ import annotations

import sys
import threading
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, Iterator, List, Tuple

import pytest

from smartenv import Env
from smartenv.watcher import FileWatcher


class FakeObserver:
    """Capture scheduling and lifecycle without creating background threads."""

    def __init__(self) -> None:
        self.daemon = False
        self.scheduled: List[Tuple[Any, str, bool]] = []
        self.started = False
        self.stopped = False
        self.joined = False

    def schedule(self, handler: Any, path: str, recursive: bool) -> None:
        """Record a watched directory."""
        self.scheduled.append((handler, path, recursive))

    def start(self) -> None:
        """Record observer startup."""
        self.started = True

    def stop(self) -> None:
        """Record observer shutdown."""
        self.stopped = True

    def join(self) -> None:
        """Record the wait for shutdown."""
        self.joined = True

    def is_alive(self) -> bool:
        """Report whether startup occurred."""
        return self.started and not self.stopped


@pytest.fixture
def observer(monkeypatch: pytest.MonkeyPatch) -> FakeObserver:
    """Provide fake optional watchdog modules and one observer instance."""
    instance = FakeObserver()
    events = ModuleType("watchdog.events")
    observers = ModuleType("watchdog.observers")
    events.FileSystemEventHandler = SimpleNamespace  # type: ignore[attr-defined]
    observers.Observer = lambda: instance  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "watchdog", ModuleType("watchdog"))
    monkeypatch.setitem(sys.modules, "watchdog.events", events)
    monkeypatch.setitem(sys.modules, "watchdog.observers", observers)
    return instance


@pytest.fixture
def config(tmp_path: Path) -> Iterator[Tuple[Env, Path]]:
    """Create and close a typed configuration backed by a temporary file."""
    path = tmp_path / ".env"
    path.write_text("PORT=8000\n", encoding="utf-8")
    env = Env({"PORT": int}, sources=[str(path)], required=["PORT"], strict=True)
    yield env, path
    env.close()


def event(path: Path, **kwargs: Any) -> SimpleNamespace:
    """Make a file event with optional move destination or directory marker."""
    return SimpleNamespace(
        src_path=str(path), is_directory=kwargs.pop("is_directory", False), **kwargs
    )


def test_watcher_schedules_each_parent_once_and_stops_idempotently(
    observer: FakeObserver, config: Tuple[Env, Path]
) -> None:
    env, path = config
    watcher = FileWatcher(env, [str(path), str(path.parent / "config.json")])
    watcher.start()
    watcher.start()
    assert len(observer.scheduled) == 1
    assert Path(observer.scheduled[0][1]) == path.parent
    assert observer.scheduled[0][2] is False
    assert observer.daemon and observer.started
    watcher.stop()
    watcher.stop()
    assert observer.stopped and observer.joined


def test_matching_event_reloads_all_sources_and_calls_callback_once(
    observer: FakeObserver, config: Tuple[Env, Path]
) -> None:
    env, path = config
    seen: List[int] = []
    watcher = FileWatcher(env, [str(path)], on_reload=lambda current: seen.append(current.PORT))
    watcher.start()
    path.write_text("PORT=9000\n", encoding="utf-8")
    observer.scheduled[0][0].on_modified(event(path))
    assert env.PORT == 9000
    assert seen == [9000]
    watcher.stop()


def test_debounce_ignores_duplicates_but_accepts_later_events(
    observer: FakeObserver, config: Tuple[Env, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    env, path = config
    times = iter([0.0, 0.25, 0.5])
    monkeypatch.setattr("smartenv.watcher.monotonic", lambda: next(times))
    seen: List[int] = []
    watcher = FileWatcher(env, [str(path)], on_reload=lambda current: seen.append(current.PORT))
    watcher.start()
    handler = observer.scheduled[0][0]
    handler.on_modified(event(path))
    path.write_text("PORT=9000\n", encoding="utf-8")
    handler.on_modified(event(path))
    assert env.PORT == 8000
    handler.on_modified(event(path))
    assert seen == [8000, 9000]
    watcher.stop()


def test_unrelated_and_directory_events_are_ignored(
    observer: FakeObserver, config: Tuple[Env, Path]
) -> None:
    env, path = config
    watcher = FileWatcher(env, [str(path)])
    watcher.start()
    path.write_text("PORT=9000\n", encoding="utf-8")
    handler = observer.scheduled[0][0]
    handler.on_modified(event(path.parent / "other.env"))
    handler.on_modified(event(path, is_directory=True))
    assert env.PORT == 8000
    watcher.stop()
    handler.on_modified(event(path))
    assert env.PORT == 8000


def test_atomic_file_replacement_reloads(observer: FakeObserver, config: Tuple[Env, Path]) -> None:
    env, path = config
    watcher = FileWatcher(env, [str(path)])
    watcher.start()
    path.write_text("PORT=9000\n", encoding="utf-8")
    observer.scheduled[0][0].on_moved(event(path.parent / ".temp", dest_path=str(path)))
    assert env.PORT == 9000
    watcher.stop()


def test_invalid_reload_survives_and_recovers_on_next_edit(
    observer: FakeObserver, config: Tuple[Env, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    env, path = config
    times = iter([0.0, 1.0])
    monkeypatch.setattr("smartenv.watcher.monotonic", lambda: next(times))
    seen: List[int] = []
    watcher = FileWatcher(env, [str(path)], on_reload=lambda current: seen.append(current.PORT))
    watcher.start()
    handler = observer.scheduled[0][0]
    path.write_text("PORT=invalid\n", encoding="utf-8")
    handler.on_modified(event(path))
    assert not env.valid
    assert any("hot_reload failed" in warning for warning in env.warnings)
    assert seen == []
    path.write_text("PORT=9000\n", encoding="utf-8")
    handler.on_modified(event(path))
    assert env.valid and env.PORT == 9000
    assert seen == [9000]
    watcher.stop()


def test_callback_failure_does_not_escape_event_handler(
    observer: FakeObserver, config: Tuple[Env, Path]
) -> None:
    env, path = config

    def fail(current: Env) -> None:
        raise RuntimeError("callback failed")

    watcher = FileWatcher(env, [str(path)], on_reload=fail)
    watcher.start()
    observer.scheduled[0][0].on_modified(event(path))
    assert any("callback failed" in warning for warning in env.warnings)
    watcher.stop()


def test_env_integration_invokes_its_callback_once(observer: FakeObserver, tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("PORT=8000\n", encoding="utf-8")
    seen: List[int] = []
    with Env(
        {"PORT": int},
        sources=[str(path)],
        hot_reload=True,
        on_reload=lambda current: seen.append(current.PORT),
    ) as env:
        path.write_text("PORT=9000\n", encoding="utf-8")
        observer.scheduled[0][0].on_modified(event(path))
        assert env.PORT == 9000
        assert seen == [9000]
    assert observer.stopped and observer.joined


def test_missing_watchdog_explains_extra(
    monkeypatch: pytest.MonkeyPatch, config: Tuple[Env, Path]
) -> None:
    env, path = config
    monkeypatch.setitem(sys.modules, "watchdog.events", None)
    with pytest.raises(ImportError, match=r"pip install smartenv\[watch\]"):
        FileWatcher(env, [str(path)]).start()
    with Env({"PORT": int}, sources=[str(path)], hot_reload=True) as watched:
        assert watched.watcher is None
        assert any("pip install smartenv[watch]" in warning for warning in watched.warnings)


def test_real_observer_reloads_and_can_close_from_callback(tmp_path: Path) -> None:
    pytest.importorskip("watchdog.observers")
    path = tmp_path / ".env"
    path.write_text("PORT=8000\n", encoding="utf-8")
    delivered = threading.Event()
    seen: List[int] = []

    def on_reload(current: Env) -> None:
        seen.append(current.PORT)
        current.close()
        delivered.set()

    with Env({"PORT": int}, sources=[str(path)], hot_reload=True, on_reload=on_reload) as env:
        assert env.watcher is not None
        path.write_text("PORT=9000\n", encoding="utf-8")
        assert delivered.wait(timeout=10), env.warnings
        assert seen == [9000]
        assert env.closed
