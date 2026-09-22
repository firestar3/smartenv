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
        self.stopped = False

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


class ManualClock:
    """Advance debounce time without sleeping in unit tests."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        """Return the current artificial monotonic time."""
        return self.now

    def advance(self, watcher: FileWatcher, seconds: float = 0.5) -> None:
        """Wake the worker after advancing its debounce clock."""
        with watcher._condition:
            self.now += seconds
            watcher._condition.notify_all()


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> ManualClock:
    """Keep the debounce clock frozen until the test advances it."""
    clock = ManualClock()
    monkeypatch.setattr("smartenv.watcher.monotonic", clock)
    return clock


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
    observer: FakeObserver, config: Tuple[Env, Path], clock: ManualClock
) -> None:
    env, path = config
    seen: List[int] = []
    delivered = threading.Event()

    def on_reload(current: Env) -> None:
        seen.append(current.PORT)
        delivered.set()

    watcher = FileWatcher(env, [str(path)], on_reload=on_reload)
    watcher.start()
    path.write_text("PORT=9000\n", encoding="utf-8")
    observer.scheduled[0][0].on_modified(event(path))
    assert env.PORT == 8000
    clock.advance(watcher)
    assert delivered.wait(timeout=5)
    assert env.PORT == 9000
    assert seen == [9000]
    watcher.stop()


def test_debounce_waits_for_final_write_in_burst(
    observer: FakeObserver, config: Tuple[Env, Path], clock: ManualClock
) -> None:
    env, path = config
    seen: List[int] = []
    delivered = threading.Event()

    def on_reload(current: Env) -> None:
        seen.append(current.PORT)
        delivered.set()

    watcher = FileWatcher(env, [str(path)], on_reload=on_reload)
    watcher.start()
    handler = observer.scheduled[0][0]
    path.write_text("PORT=", encoding="utf-8")
    handler.on_modified(event(path))
    clock.advance(watcher, 0.25)
    path.write_text("PORT=9000\n", encoding="utf-8")
    handler.on_modified(event(path))
    clock.advance(watcher, 0.25)
    assert env.PORT == 8000
    assert not delivered.is_set()
    clock.advance(watcher, 0.25)
    assert delivered.wait(timeout=5)
    assert seen == [9000]
    assert env.warnings == []
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


def test_atomic_file_replacement_reloads(
    observer: FakeObserver, config: Tuple[Env, Path], clock: ManualClock
) -> None:
    env, path = config
    delivered = threading.Event()
    watcher = FileWatcher(env, [str(path)], on_reload=lambda current: delivered.set())
    watcher.start()
    path.write_text("PORT=9000\n", encoding="utf-8")
    observer.scheduled[0][0].on_moved(event(path.parent / ".temp", dest_path=str(path)))
    clock.advance(watcher)
    assert delivered.wait(timeout=5)
    assert env.PORT == 9000
    watcher.stop()


def test_invalid_reload_survives_and_recovers_on_next_edit(
    observer: FakeObserver,
    config: Tuple[Env, Path],
    monkeypatch: pytest.MonkeyPatch,
    clock: ManualClock,
) -> None:
    env, path = config
    failed = threading.Event()
    delivered = threading.Event()
    add_warning = env._add_warning

    def warning(message: str) -> None:
        add_warning(message)
        failed.set()

    monkeypatch.setattr(env, "_add_warning", warning)
    seen: List[int] = []

    def on_reload(current: Env) -> None:
        seen.append(current.PORT)
        delivered.set()

    watcher = FileWatcher(env, [str(path)], on_reload=on_reload)
    watcher.start()
    handler = observer.scheduled[0][0]
    path.write_text("PORT=invalid\n", encoding="utf-8")
    handler.on_modified(event(path))
    clock.advance(watcher)
    assert failed.wait(timeout=5)
    assert env.valid and env.PORT == 8000
    assert any("hot_reload failed" in warning for warning in env.warnings)
    assert seen == []
    path.write_text("PORT=9000\n", encoding="utf-8")
    handler.on_modified(event(path))
    clock.advance(watcher)
    assert delivered.wait(timeout=5)
    assert env.valid and env.PORT == 9000
    assert seen == [9000]
    watcher.stop()


def test_callback_failure_does_not_escape_event_handler(
    observer: FakeObserver,
    config: Tuple[Env, Path],
    monkeypatch: pytest.MonkeyPatch,
    clock: ManualClock,
) -> None:
    env, path = config
    failed = threading.Event()
    add_warning = env._add_warning

    def warning(message: str) -> None:
        add_warning(message)
        failed.set()

    monkeypatch.setattr(env, "_add_warning", warning)

    def fail(current: Env) -> None:
        raise RuntimeError("callback failed")

    watcher = FileWatcher(env, [str(path)], on_reload=fail)
    watcher.start()
    observer.scheduled[0][0].on_modified(event(path))
    clock.advance(watcher)
    assert failed.wait(timeout=5)
    assert any("callback failed" in warning for warning in env.warnings)
    watcher.stop()


def test_env_integration_invokes_its_callback_once(
    observer: FakeObserver, tmp_path: Path, clock: ManualClock
) -> None:
    path = tmp_path / ".env"
    path.write_text("PORT=8000\n", encoding="utf-8")
    seen: List[int] = []
    delivered = threading.Event()

    def on_reload(current: Env) -> None:
        seen.append(current.PORT)
        delivered.set()

    with Env(
        {"PORT": int},
        sources=[str(path)],
        hot_reload=True,
        on_reload=on_reload,
    ) as env:
        path.write_text("PORT=9000\n", encoding="utf-8")
        observer.scheduled[0][0].on_modified(event(path))
        watcher = env.watcher
        assert watcher is not None
        clock.advance(watcher)
        assert delivered.wait(timeout=5)
        assert env.PORT == 9000
        assert seen == [9000]
    assert observer.stopped and observer.joined


def test_missing_watchdog_explains_extra(
    monkeypatch: pytest.MonkeyPatch, config: Tuple[Env, Path]
) -> None:
    env, path = config
    monkeypatch.setitem(sys.modules, "watchdog.events", None)
    with pytest.raises(ImportError, match=r"pip install smartenv-config\[watch\]"):
        FileWatcher(env, [str(path)]).start()
    with Env({"PORT": int}, sources=[str(path)], hot_reload=True) as watched:
        assert watched.watcher is None
        assert any("pip install smartenv-config[watch]" in warning for warning in watched.warnings)


def test_empty_file_list_needs_no_dependency_or_threads(
    monkeypatch: pytest.MonkeyPatch, config: Tuple[Env, Path]
) -> None:
    env, _ = config
    monkeypatch.setitem(sys.modules, "watchdog.events", None)
    watcher = FileWatcher(env, [])
    watcher.start()
    assert watcher._observer is None and watcher._worker is None
    watcher.stop()


def test_stop_cancels_pending_reload(
    observer: FakeObserver, config: Tuple[Env, Path], clock: ManualClock
) -> None:
    env, path = config
    seen: List[int] = []
    watcher = FileWatcher(env, [str(path)], on_reload=lambda current: seen.append(current.PORT))
    watcher.start()
    path.write_text("PORT=9000\n", encoding="utf-8")
    observer.scheduled[0][0].on_modified(event(path))
    watcher.stop()
    clock.advance(watcher)
    assert watcher._worker is not None and not watcher._worker.is_alive()
    assert env.PORT == 8000 and seen == []


def test_events_during_reload_are_serialized_and_delivered_afterwards(
    observer: FakeObserver,
    config: Tuple[Env, Path],
    clock: ManualClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env, path = config
    entered = threading.Event()
    release = threading.Event()
    delivered = threading.Event()
    reload = env.reload
    calls: List[int] = []
    seen: List[int] = []

    def slow_reload() -> None:
        calls.append(len(calls) + 1)
        if len(calls) == 1:
            entered.set()
            assert release.wait(timeout=5)
        reload()

    def on_reload(current: Env) -> None:
        seen.append(current.PORT)
        if len(seen) == 2:
            delivered.set()

    monkeypatch.setattr(env, "reload", slow_reload)
    watcher = FileWatcher(env, [str(path)], on_reload=on_reload)
    watcher.start()
    try:
        handler = observer.scheduled[0][0]
        handler.on_modified(event(path))
        clock.advance(watcher)
        assert entered.wait(timeout=5)
        path.write_text("PORT=9000\n", encoding="utf-8")
        handler.on_modified(event(path))
        handler.on_modified(event(path))
        clock.advance(watcher)
        assert calls == [1]
        release.set()
        assert delivered.wait(timeout=5)
        assert calls == [1, 2]
        assert seen == [9000, 9000]
    finally:
        release.set()
        watcher.stop()


def test_stop_waits_for_running_reload_and_skips_additional_callback(
    observer: FakeObserver,
    config: Tuple[Env, Path],
    clock: ManualClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env, path = config
    entered = threading.Event()
    release = threading.Event()
    stopping = threading.Event()
    stopped = threading.Event()
    callbacks: List[Env] = []

    def slow_reload() -> None:
        entered.set()
        assert release.wait(timeout=5)

    original_stop = observer.stop

    def observer_stop() -> None:
        original_stop()
        stopping.set()

    monkeypatch.setattr(env, "reload", slow_reload)
    monkeypatch.setattr(observer, "stop", observer_stop)
    watcher = FileWatcher(env, [str(path)], on_reload=callbacks.append)
    watcher.start()

    def stop() -> None:
        watcher.stop()
        stopped.set()

    stopper = threading.Thread(target=stop)
    try:
        observer.scheduled[0][0].on_modified(event(path))
        clock.advance(watcher)
        assert entered.wait(timeout=5)
        stopper.start()
        assert stopping.wait(timeout=5)
        assert not stopped.is_set()
        with pytest.raises(RuntimeError, match="still stopping"):
            watcher.start()
        release.set()
        assert stopped.wait(timeout=5)
        assert callbacks == []
        assert watcher._worker is not None and not watcher._worker.is_alive()
    finally:
        release.set()
        stopper.join(timeout=5)
        watcher.stop()


def test_watcher_can_restart_after_stop(
    observer: FakeObserver, config: Tuple[Env, Path], clock: ManualClock
) -> None:
    env, path = config
    delivered = threading.Event()
    watcher = FileWatcher(env, [str(path)], on_reload=lambda current: delivered.set())
    watcher.start()
    original_worker = watcher._worker
    watcher.stop()
    watcher.start()
    path.write_text("PORT=9000\n", encoding="utf-8")
    observer.scheduled[-1][0].on_modified(event(path))
    clock.advance(watcher)
    assert delivered.wait(timeout=5)
    assert env.PORT == 9000
    assert watcher._worker is not original_worker
    watcher.stop()


@pytest.mark.parametrize("stage", ["schedule", "start"])
def test_observer_start_failure_cleans_up(
    observer: FakeObserver,
    config: Tuple[Env, Path],
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
) -> None:
    env, path = config

    def fail(*args: Any, **kwargs: Any) -> None:
        if stage == "start":
            observer.started = True
        raise OSError("unable to watch directory")

    monkeypatch.setattr(observer, stage, fail)
    watcher = FileWatcher(env, [str(path)])
    with pytest.raises(OSError, match="unable to watch directory"):
        watcher.start()
    assert observer.stopped
    assert observer.joined == (stage == "start")
    assert watcher._observer is None and watcher._worker is None
    watcher.stop()


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
