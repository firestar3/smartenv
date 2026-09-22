"""Source abstractions for smartenv.

A *source* resolves a flat ``{KEY: VALUE}`` mapping from somewhere: the process
environment, a ``.env`` file, a JSON/TOML/YAML document or a cloud secret
manager. Every source implements :class:`BaseSource`, and the file backed ones
share the path handling of :class:`FileSource`.

Values produced by sources are always strings so that
:func:`smartenv.casters.cast` can turn them into the types declared by a schema.

Example:
    >>> from smartenv.sources import resolve_source
    >>> resolve_source("os").name
    'os'
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import math
import threading
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Union

from smartenv.exceptions import MissingSourceError, SourceLoadError

__all__ = ["BaseSource", "CloudSource", "FileSource", "flatten_mapping", "parse_secret_payload"]


class BaseSource(ABC):
    """Abstract base class for configuration sources.

    Subclasses must provide :attr:`name` and :meth:`load`.

    Attributes:
        name: Human readable identifier of the source, e.g. ``"os"`` or ``".env"``.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the identifier of the source.

        Returns:
            The identifier, typically ``"os"`` or the file name of the source.
        """

    @abstractmethod
    def load(self) -> Dict[str, str]:
        """Return the key/value pairs provided by the source.

        Implementations must be idempotent and free of side effects other than
        reading from the backing store, so that a source can be loaded from
        several threads.

        Returns:
            A mapping of key to string value.

        Raises:
            MissingSourceError: If the source does not exist.
            SourceLoadError: If the source exists but cannot be parsed.
        """

    def __repr__(self) -> str:
        """Return a debug representation of the source.

        Returns:
            A string such as ``"<OsSource name='os'>"``.
        """
        return f"<{type(self).__name__} name={self.name!r}>"


class CloudSource(BaseSource):
    """Base class for sources backed by a cloud secret manager.

    Subclasses implement :meth:`_fetch` with the provider specific SDK calls.
    This class adds the features shared by every cloud source:

    * a thread safe, per instance result :attr:`cache` (opt out with
      ``cache=False``), with optional expiration via ``cache_ttl``;
    * :meth:`aload`, an ``await``-able variant of :meth:`load` that runs the
      (synchronous) SDK calls on a worker thread and therefore also works on
      Python 3.8;
    * :meth:`cache_clear` to drop the cached result.

    Implementations must be free of side effects other than reading from the
    backing store, so that a source can be loaded from several threads.

    Args:
        cache: When ``True``, successful :meth:`load` results are cached.
        cache_ttl: Positive finite cache lifetime in seconds. ``None`` caches
            indefinitely. Expired values refresh on the next :meth:`load`;
            no background polling occurs. Ignored when ``cache=False``.

    Attributes:
        cache: Whether successful fetches are cached.
        cache_ttl: Cache lifetime in seconds, or ``None`` for no expiration.
    """

    def __init__(self, cache: bool = True, cache_ttl: Optional[float] = None) -> None:
        if cache_ttl is not None and (
            isinstance(cache_ttl, bool)
            or not isinstance(cache_ttl, (int, float))
            or not math.isfinite(cache_ttl)
            or cache_ttl <= 0
        ):
            raise ValueError("cache_ttl must be a positive finite number of seconds or None")
        self.cache = cache
        self.cache_ttl = cache_ttl
        self._cache_lock = threading.Lock()
        self._cached: Optional[Dict[str, str]] = None
        self._cached_at: Optional[float] = None

    @abstractmethod
    def _fetch(self) -> Dict[str, str]:
        """Return the key/value pairs provided by the cloud provider.

        Implementations perform the provider SDK calls here and translate
        provider errors into :class:`smartenv.exceptions.CloudAuthError`.

        Returns:
            A mapping of key to string value.

        Raises:
            CloudAuthError: If the provider cannot be reached or authenticated.
        """

    def load(self) -> Dict[str, str]:
        """Return the key/value pairs provided by the cloud provider.

        The result is served from the cache when caching is enabled and a
        previous call succeeded and its lifetime has not expired. Failed
        refreshes raise without extending the lifetime or serving stale data.

        Returns:
            A new dictionary of key to string value; mutating it never affects
            the cached result.

        Raises:
            CloudAuthError: If the provider cannot be reached or authenticated.
        """
        with self._cache_lock:
            if not self.cache:
                return dict(self._fetch())
            expired = (
                self.cache_ttl is not None
                and self._cached_at is not None
                and time.monotonic() - self._cached_at >= self.cache_ttl
            )
            if self._cached is None or expired:
                self._cached = dict(self._fetch())
                self._cached_at = time.monotonic()
            return dict(self._cached)

    async def aload(self) -> Dict[str, str]:
        """Return the key/value pairs by running :meth:`load` on a worker thread.

        Returns:
            A new dictionary of key to string value.

        Raises:
            CloudAuthError: If the provider cannot be reached or authenticated.
        """
        loop = asyncio.get_running_loop()
        context = contextvars.copy_context()
        return await loop.run_in_executor(None, context.run, self.load)

    def cache_clear(self) -> None:
        """Drop the cached result so the next :meth:`load` fetches again."""
        with self._cache_lock:
            self._cached = None
            self._cached_at = None


def parse_secret_payload(raw: str, default_key: str = "SECRET") -> Dict[str, str]:
    """Turn a raw secret payload into a flat string mapping.

    A payload that parses as a JSON object is flattened with
    :func:`flatten_mapping` (nested keys are uppercased and joined with ``__``),
    so ``{"database": {"host": "db"}}`` becomes
    ``{"DATABASE__HOST": "db"}``. Any other payload — including JSON that is
    not an object, such as a bare string or array — is returned as a single
    ``{default_key: value}`` entry, preserving its original whitespace.

    Args:
        raw: The raw payload text, e.g. the body of a cloud secret.
        default_key: Key to use for a payload that is not a JSON object.

    Returns:
        A flat dictionary of key to string value.

    Example:
        >>> parse_secret_payload('{"PORT": "8080"}')
        {'PORT': '8080'}
        >>> parse_secret_payload("just-a-token")
        {'SECRET': 'just-a-token'}
    """
    text = raw.strip()
    if not text.startswith("{"):
        return {default_key: raw}
    try:
        parsed = json.loads(text)
    except ValueError:
        return {default_key: raw}
    if not isinstance(parsed, Mapping):
        return {default_key: raw}
    return flatten_mapping(parsed)


class FileSource(BaseSource):
    """Base class for sources backed by a single file.

    Args:
        path: Path of the file. It is stored as a :class:`pathlib.Path` and
            nothing is read from disk until :meth:`load` is called.

    Attributes:
        path: Path of the backing file.
    """

    def __init__(self, path: Union[str, Path]) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        """Return the path of the backing file.

        Returns:
            The :class:`pathlib.Path` given to the constructor.
        """
        return self._path

    @property
    def name(self) -> str:
        """Return the file name of the backing file.

        Returns:
            The last path component, e.g. ``".env"`` or ``"settings.json"``.
        """
        return self._path.name

    def exists(self) -> bool:
        """Report whether the backing file exists.

        Returns:
            ``True`` when the path points at an existing regular file.
        """
        return self._path.is_file()

    def read_text(self) -> str:
        """Read the backing file as UTF-8 text.

        A leading UTF-8 byte order mark is stripped so it can never leak into the
        first key of a parsed document.

        Returns:
            The decoded content of the file.

        Raises:
            MissingSourceError: If the file does not exist or is not a regular file.
            SourceLoadError: If the file exists but cannot be read.
        """
        if not self.exists():
            raise MissingSourceError(str(self._path))
        try:
            text = self._path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise SourceLoadError(str(self._path), reason=str(exc)) from exc
        if text.startswith("\ufeff"):
            return text[1:]
        return text


def flatten_mapping(data: Mapping[Any, Any], separator: str = "__") -> Dict[str, str]:
    """Flatten a nested mapping into uppercase, string valued keys.

    Nested key parts are uppercased and joined with ``separator``; leaf values are
    converted to strings, so the result can be used as an environment mapping::

        {"database": {"host": "localhost", "port": 5432}}
        -> {"DATABASE__HOST": "localhost", "DATABASE__PORT": "5432"}

    Lists and tuples are JSON encoded (``["a", "b"]`` becomes ``'["a","b"]'``),
    which :func:`smartenv.casters.cast` understands as a list, booleans become
    ``"true"``/``"false"``, ``None`` becomes ``""`` and any other object is
    converted with ``str()``. Nested mappings that are empty contribute no keys.

    Args:
        data: Mapping to flatten; keys are converted with ``str()`` before being
            uppercased.
        separator: Text inserted between the parts of a nested key.

    Returns:
        A new, flat dictionary of ``str`` to ``str``, in document order.

    Example:
        >>> flatten_mapping({"db": {"port": 5432}})
        {'DB__PORT': '5432'}
    """
    flattened: Dict[str, str] = {}
    _flatten_into(data, "", separator, flattened)
    return flattened


def _flatten_into(
    data: Mapping[Any, Any], prefix: str, separator: str, out: Dict[str, str]
) -> None:
    """Recursively copy ``data`` into ``out`` as flat string pairs.

    Args:
        data: Mapping to flatten.
        prefix: Already uppercased key prefix of the current nesting level.
        separator: Text inserted between the parts of a nested key.
        out: Result mapping, mutated in place.
    """
    for raw_key, value in data.items():
        key = str(raw_key).upper()
        full_key = f"{prefix}{separator}{key}" if prefix else key
        if isinstance(value, Mapping):
            _flatten_into(value, full_key, separator, out)
        else:
            out[full_key] = _stringify_value(value)


def _stringify_value(value: Any) -> str:
    """Convert a leaf value of a structured document to its string form.

    Args:
        value: Any value found in a JSON, TOML or YAML document.

    Returns:
        ``""`` for ``None``, ``"true"``/``"false"`` for booleans, compact JSON for
        lists and tuples, and the value itself (or its ``str()``) otherwise.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return json.dumps(list(value), separators=(",", ":"), ensure_ascii=False, default=str)
    return str(value)
