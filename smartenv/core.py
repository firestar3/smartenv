"""The :class:`Env` façade: multi-source loading, validation and typed access.

:class:`Env` ties the layers of smartenv together: it reads key/value pairs from
one or more *sources*, casts them with the types declared in a *schema* and
validates the result before exposing it::

    from smartenv import Env

    env = Env({"PORT": int, "DEBUG": bool}, sources=["os", ".env"], required=["PORT"])

    env.PORT       # 8080
    env["DEBUG"]   # True
    env.get("MISSING", "fallback")
    env.dict()     # {"PORT": 8080, "DEBUG": True}

Loading rules:
    * sources are read left to right and the **first** source that defines a key
      wins, so ``["os", ".env"]`` lets real environment variables override a file;
    * a source file that does not exist is skipped with a warning, unless
      ``strict=True``, where it raises :class:`~smartenv.exceptions.MissingSourceError`;
    * a source that exists but cannot be parsed always raises
      :class:`~smartenv.exceptions.SourceLoadError`;
    * only keys declared in the schema are exposed; everything else stays in the
      sources (declare a key as ``str`` or ``Any`` to pass it through);
    * ``strict=True`` turns validation errors into a
      :class:`~smartenv.exceptions.ValidationError`; otherwise the errors are kept
      in :attr:`Env.errors` and the offending keys are simply unavailable.

Example:
    >>> from smartenv import Env
    >>> class MemorySource:
    ...     name = "memory"
    ...     def load(self):
    ...         return {"PORT": "8080", "DEBUG": "yes"}
    >>> env = Env({"PORT": int, "DEBUG": bool}, sources=[MemorySource()])
    >>> env.PORT
    8080
    >>> env["DEBUG"]
    True
    >>> env.dict()
    {'PORT': 8080, 'DEBUG': True}
"""

from __future__ import annotations

import json
import threading
from types import TracebackType
from typing import (
    Any,
    Callable,
    Dict,
    Iterator,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
    Type,
    Union,
    get_args,
)

from smartenv.casters import cast
from smartenv.exceptions import (
    CastError,
    MissingKeyError,
    MissingSourceError,
    ValidationError,
)
from smartenv.schema import normalize_schema
from smartenv.sources import BaseSource, FileSource, resolve_source
from smartenv.validators import ValidationResult, Validator, validate

__all__ = ["Env"]

_SENSITIVE_MARKERS: Tuple[str, ...] = (
    "AUTH",
    "CERT",
    "CREDENTIAL",
    "KEY",
    "PASSWORD",
    "PASSWD",
    "PRIVATE",
    "SECRET",
    "TOKEN",
)
"""Key name fragments that mark a value as sensitive; such values are masked in repr."""

_MASK: str = "***"
"""Replacement text used for sensitive values."""


class Env:
    """Typed, validated view over one or more configuration sources.

    Args:
        schema: Mapping of key to type, or a pydantic model class (see
            :func:`smartenv.schema.normalize_schema`).
        sources: Source strings understood by
            :func:`smartenv.sources.resolve_source` or ready made source objects
            exposing ``load()``. Defaults to ``["os"]`` when omitted.
        required: Keys that must be present and non empty.
        strict: When ``True``, validation errors and missing source files raise
            instead of being collected in :attr:`errors` / :attr:`warnings`.
        hot_reload: When ``True``, watch the file sources and reload on change.
            Requires the optional ``watchdog`` dependency; a warning is recorded
            when it is unavailable.
        validators: Custom validators receiving the *cast* value, see
            :func:`smartenv.validators.validate`.
        on_reload: Callback invoked with this instance after a successful
            :meth:`reload`.

    Attributes:
        errors: Validation errors from the last load.
        warnings: Non fatal findings from the last load.
        valid: ``True`` when the last load produced no validation error.
    """

    def __init__(
        self,
        schema: Union[Mapping[str, Any], type],
        sources: Optional[Sequence[Union[str, BaseSource]]] = None,
        required: Optional[Sequence[str]] = None,
        strict: bool = False,
        hot_reload: bool = False,
        validators: Optional[Mapping[str, Validator]] = None,
        on_reload: Optional[Callable[[Env], None]] = None,
    ) -> None:
        self._lock = threading.RLock()
        self._schema: Dict[str, Any] = normalize_schema(schema)
        self._required: Tuple[str, ...] = tuple(dict.fromkeys(required or ()))
        self._strict = bool(strict)
        self._hot_reload = bool(hot_reload)
        self._custom_validators: Dict[str, Validator] = dict(validators or {})
        self._on_reload = on_reload
        self._values: Dict[str, Any] = {}
        self._errors: List[str] = []
        self._warnings: List[str] = []
        self._watcher: Optional[Any] = None
        self._closed = False

        if sources is None:
            specs: Sequence[Union[str, BaseSource]] = ("os",)
        else:
            specs = sources
        self._sources: Tuple[BaseSource, ...] = tuple(self._build_source(spec) for spec in specs)

        self._refresh()
        if self._hot_reload:
            self._start_watcher()

    # --- introspection -------------------------------------------------------

    @property
    def schema(self) -> Dict[str, Any]:
        """Return a copy of the normalized schema.

        Returns:
            A mapping of key to type hint, in declaration order.
        """
        return dict(self._schema)

    @property
    def required(self) -> Tuple[str, ...]:
        """Return the keys that must be present and non empty.

        Returns:
            The required keys, without duplicates, in declaration order.
        """
        return self._required

    @property
    def strict(self) -> bool:
        """Return whether strict mode is enabled.

        Returns:
            ``True`` when validation errors and missing source files raise.
        """
        return self._strict

    @property
    def hot_reload(self) -> bool:
        """Return whether a hot reload watcher was requested.

        Returns:
            The value passed to the constructor, regardless of whether the watcher
            could be started.
        """
        return self._hot_reload

    @property
    def sources(self) -> Tuple[BaseSource, ...]:
        """Return the source objects, in priority order.

        Returns:
            The resolved sources; the first one that defines a key wins.
        """
        return self._sources

    @property
    def errors(self) -> List[str]:
        """Return the validation errors of the last load.

        Returns:
            A copy of the error list, empty when the load was valid.
        """
        with self._lock:
            return list(self._errors)

    @property
    def warnings(self) -> List[str]:
        """Return the warnings of the last load.

        Returns:
            A copy of the warning list, including skipped sources and validator
            findings.
        """
        with self._lock:
            return list(self._warnings)

    @property
    def valid(self) -> bool:
        """Report whether the last load produced no validation error.

        Returns:
            ``True`` when :attr:`errors` is empty.
        """
        with self._lock:
            return not self._errors

    # --- access patterns -----------------------------------------------------

    def __getattr__(self, name: str) -> Any:
        """Return a resolved value by attribute name.

        Args:
            name: Key to look up.

        Returns:
            The cast value stored for ``name``.

        Raises:
            AttributeError: For private and dunder names, so ``hasattr``, ``copy``
                and ``pickle`` keep behaving normally.
            MissingKeyError: If ``name`` is not part of the resolved values.

        Example:
            >>> from smartenv import Env
            >>> class MemorySource:
            ...     name = "memory"
            ...     def load(self):
            ...         return {"PORT": "8080"}
            >>> Env({"PORT": int}, sources=[MemorySource()]).PORT
            8080
        """
        if name.startswith("_"):
            raise AttributeError(f"{type(self).__name__!r} object has no attribute {name!r}")
        with self._lock:
            if name in self._values:
                return self._values[name]
        raise MissingKeyError(name, message=self._missing_message(name))

    def __getitem__(self, key: str) -> Any:
        """Return a resolved value by key.

        Args:
            key: Key to look up.

        Returns:
            The cast value stored for ``key``.

        Raises:
            MissingKeyError: If ``key`` is not part of the resolved values.
        """
        with self._lock:
            if key in self._values:
                return self._values[key]
        raise MissingKeyError(key, message=self._missing_message(key))

    def get(self, key: str, default: Any = None) -> Any:
        """Return a resolved value, or ``default`` when the key is not set.

        Args:
            key: Key to look up.
            default: Value returned when ``key`` is unavailable.

        Returns:
            The cast value, or ``default``.
        """
        with self._lock:
            return self._values.get(key, default)

    def dict(self) -> Dict[str, Any]:
        """Return every resolved value as a plain dictionary.

        Returns:
            A snapshot copy, in schema order, safe to mutate.
        """
        with self._lock:
            return dict(self._values)

    def json(self, **kwargs: Any) -> str:
        """Return every resolved value as a JSON document.

        Args:
            **kwargs: Extra arguments forwarded to :func:`json.dumps`, e.g.
                ``indent=2``.

        Returns:
            The serialized values.
        """
        return json.dumps(self.dict(), **kwargs)

    def __contains__(self, key: object) -> bool:
        """Report whether a key is part of the resolved values.

        Args:
            key: Key to test, usually a string.

        Returns:
            ``True`` when the key was set in a source *and* cast successfully.
        """
        with self._lock:
            return key in self._values

    def __len__(self) -> int:
        """Return the number of resolved values.

        Returns:
            The count of successfully cast keys.
        """
        with self._lock:
            return len(self._values)

    def __iter__(self) -> Iterator[str]:
        """Iterate over the resolved keys.

        The key list is snapshotted first, so iteration stays valid while another
        thread calls :meth:`reload`.

        Returns:
            An iterator over a copy of the key list.
        """
        with self._lock:
            return iter(list(self._values))

    def __repr__(self) -> str:
        """Return a debug representation with sensitive values masked.

        Keys are sorted and any key whose name contains a sensitive marker
        (``KEY``, ``PASSWORD``, ``SECRET``, ``TOKEN``, ...) is shown as ``***``.

        Returns:
            A string such as ``"Env(PORT=8080, SECRET_KEY='***')"``.
        """
        with self._lock:
            items = sorted(self._values.items())
        body = ", ".join(f"{key}={_masked(key, value)!r}" for key, value in items)
        return f"{type(self).__name__}({body})"

    # --- lifecycle -----------------------------------------------------------

    def reload(self) -> None:
        """Re-read every source, re-validate and swap in the new values.

        The swap is atomic: concurrent readers see either the previous or the new
        snapshot. When ``on_reload`` was supplied it is called with this instance
        afterwards.

        Raises:
            ValidationError: If ``strict`` is enabled and the new values are invalid.
            MissingSourceError: If ``strict`` is enabled and a source is missing.
            SourceLoadError: If a source exists but cannot be parsed.
        """
        self._refresh()
        if self._on_reload is not None:
            self._on_reload(self)

    def close(self) -> None:
        """Stop the hot reload watcher, if one is running.

        Calling it more than once is harmless; values stay readable afterwards.
        """
        watcher = self._watcher
        self._watcher = None
        self._closed = True
        stop = getattr(watcher, "stop", None)
        if callable(stop):
            stop()

    @property
    def closed(self) -> bool:
        """Report whether :meth:`close` has been called.

        Returns:
            ``True`` once the watcher has been stopped.
        """
        return self._closed

    @property
    def watcher(self) -> Optional[Any]:
        """Return the running hot reload watcher.

        Returns:
            The watcher object, or ``None`` when hot reload is off, unavailable or
            already closed.
        """
        return self._watcher

    def __enter__(self) -> Env:
        """Enter the runtime context.

        Returns:
            This instance.
        """
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_value: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> None:
        """Leave the runtime context, stopping the watcher.

        Args:
            exc_type: Type of the propagating exception, if any.
            exc_value: Instance of the propagating exception, if any.
            traceback: Traceback of the propagating exception, if any.
        """
        self.close()

    # --- internals -----------------------------------------------------------

    @staticmethod
    def _build_source(spec: Union[str, BaseSource]) -> BaseSource:
        """Resolve a single source specification.

        Args:
            spec: A source string understood by
                :func:`smartenv.sources.resolve_source`, or a ready made source
                object exposing ``load()``.

        Returns:
            The source instance.

        Raises:
            ValueError: If ``spec`` is a string that names no known source.
            TypeError: If ``spec`` is neither a string nor source like.
        """
        if isinstance(spec, str):
            return resolve_source(spec)
        candidate: Any = spec
        if callable(getattr(candidate, "load", None)):
            source: BaseSource = candidate
            return source
        raise TypeError(
            f"sources must be strings or objects with a load() method, got {type(spec).__name__!r}"
        )

    def _missing_message(self, key: str) -> str:
        """Explain why ``key`` could not be resolved.

        Args:
            key: Key that was requested.

        Returns:
            A message that distinguishes required, declared and undeclared keys.
        """
        if key in self._required:
            return f"required key {key!r} is not set in any source"
        if key in self._schema:
            return f"key {key!r} is declared in the schema but not set in any source"
        return f"key {key!r} is not declared in the schema and not set in any source"

    def _refresh(self) -> ValidationResult:
        """Load every source, validate the values and swap in a fresh snapshot.

        Returns:
            The validation report for the freshly loaded values.

        Raises:
            ValidationError: If ``strict`` is enabled and validation failed.
            MissingSourceError: If ``strict`` is enabled and a source is missing.
            SourceLoadError: If a source exists but cannot be parsed.
        """
        raw, warnings = self._collect()
        result = validate(raw, self._schema, self._required, self._custom_validators or None)
        warnings.extend(result.warnings)
        values = self._coerce(raw)
        with self._lock:
            self._values = values
            self._errors = list(result.errors)
            self._warnings = list(dict.fromkeys(warnings))
        if self._strict and not result.is_valid:
            raise ValidationError(errors=result.errors, warnings=result.warnings)
        return result

    def _collect(self) -> Tuple[Dict[str, str], List[str]]:
        """Load every source in priority order.

        Returns:
            ``(raw_values, warnings)``. The first source that defines a key wins,
            so earlier sources have priority over later ones.

        Raises:
            MissingSourceError: If a source is missing and ``strict`` is enabled.
            SourceLoadError: If a source exists but cannot be parsed.
        """
        raw: Dict[str, str] = {}
        warnings: List[str] = []
        for source in self._sources:
            name = _source_name(source)
            if isinstance(source, FileSource) and not source.exists():
                message = f"source {name!r} does not exist and was skipped"
                if self._strict:
                    raise MissingSourceError(str(source.path), message=message)
                warnings.append(message)
                continue
            try:
                loaded = source.load()
            except MissingSourceError as exc:
                if self._strict:
                    raise
                warnings.append(str(exc))
                continue
            for key, value in loaded.items():
                if key not in raw:
                    raw[key] = value
        return raw, warnings

    def _coerce(self, raw: Mapping[str, str]) -> Dict[str, Any]:
        """Cast the raw values of the declared keys to their schema types.

        Keys that are unset, or that fail to cast, are omitted: a failure is
        already reported by :func:`smartenv.validators.validate`. A key declared as
        ``Optional[X]`` keeps its slot with the value ``None`` when it is empty.

        Args:
            raw: Raw key/value pairs collected from the sources.

        Returns:
            The cast values, in schema order.
        """
        coerced: Dict[str, Any] = {}
        for key, type_hint in self._schema.items():
            if key not in raw:
                continue
            value = raw[key]
            if _is_unset(value) and not _allows_none(type_hint):
                continue
            try:
                coerced[key] = cast(value, type_hint, key=key)
            except CastError:
                continue
        return coerced

    def _start_watcher(self) -> None:
        """Start the file watcher that powers ``hot_reload``.

        The watcher is optional: when ``smartenv.watcher`` or its ``watchdog``
        dependency is unavailable a warning is recorded instead of failing. The
        watcher object must expose ``start()`` and ``stop()`` and call
        :meth:`reload` whenever a watched file changes.
        """
        try:
            from smartenv.watcher import FileWatcher
        except ImportError as exc:
            self._add_warning(
                f"hot_reload requested but the watcher is unavailable ({exc}); "
                "install it with: pip install smartenv[watch]"
            )
            return
        try:
            watcher = FileWatcher(
                self,
                [str(source.path) for source in self._sources if isinstance(source, FileSource)],
            )
            watcher.start()
        except Exception as exc:  # A broken watcher must never break the load.
            self._add_warning(f"hot_reload could not start the watcher: {exc}")
            return
        self._watcher = watcher

    def _add_warning(self, message: str) -> None:
        """Append a warning to the report of the current load.

        Args:
            message: Warning text; duplicates are ignored.
        """
        with self._lock:
            if message not in self._warnings:
                self._warnings.append(message)


def _source_name(source: BaseSource) -> str:
    """Return a display name for a source.

    Args:
        source: Any source like object.

    Returns:
        Its ``name`` when that is a string, otherwise the class name.
    """
    name = getattr(source, "name", None)
    return name if isinstance(name, str) else type(source).__name__


def _is_unset(value: Any) -> bool:
    """Report whether a raw value counts as "not set".

    Args:
        value: Raw value read from a source.

    Returns:
        ``True`` for ``None`` and for strings that are empty or whitespace only.
    """
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return False


def _allows_none(type_hint: Any) -> bool:
    """Report whether a schema type accepts ``None``.

    Args:
        type_hint: Type or ``typing`` construct declared in the schema.

    Returns:
        ``True`` for ``Any``, ``object``, ``NoneType`` and unions containing
        ``None`` such as ``Optional[int]``.
    """
    if type_hint is Any or type_hint is object or type_hint is None:
        return True
    if type_hint is type(None):
        return True
    return type(None) in get_args(type_hint)


def _masked(key: str, value: Any) -> Any:
    """Mask a value when its key looks sensitive.

    Args:
        key: Key the value belongs to.
        value: The value itself.

    Returns:
        ``"***"`` when the upper cased key contains a sensitive marker, otherwise
        the value unchanged.
    """
    upper = key.upper()
    for marker in _SENSITIVE_MARKERS:
        if marker in upper:
            return _MASK
    return value
