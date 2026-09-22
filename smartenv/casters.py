"""Type casting primitives used by smartenv.

Environment variables and configuration files are *text*; smartenv turns that
text into real Python objects based on a schema. :func:`cast` is the single
entry point for that conversion and understands plain types, ``typing``
generics and arbitrary callables.

Examples:
    >>> from typing import List, Optional
    >>> cast("42", int)
    42
    >>> cast("a, b", List[str])
    ['a', 'b']
    >>> cast("null", Optional[int]) is None
    True
"""

from __future__ import annotations

import json
import types
import typing
from typing import Any, Callable, Dict, List, Tuple

from smartenv.exceptions import CastError

__all__ = ["FALSE_VALUES", "TRUE_VALUES", "can_cast", "cast"]

TRUE_VALUES: Tuple[str, ...] = ("true", "1", "yes", "on")
"""Strings accepted as ``True`` (compared case insensitively, whitespace ignored)."""

FALSE_VALUES: Tuple[str, ...] = ("false", "0", "no", "off")
"""Strings accepted as ``False`` (compared case insensitively, whitespace ignored)."""

_NONE_VALUES: Tuple[str, ...] = ("", "null", "none")
"""Strings accepted as ``None`` when the target type allows ``None``."""

_UNION_ORIGINS: Tuple[Any, ...] = (typing.Union,)
_union_type = getattr(types, "UnionType", None)
if _union_type is not None:  # Python 3.10+ writes unions as ``int | None``.
    _UNION_ORIGINS = (typing.Union, _union_type)


def cast(value: Any, target_type: Any, key: str = "") -> Any:
    """Convert ``value`` to ``target_type``.

    Supported targets are ``str``, ``int``, ``float``, ``bool``, ``bytes``,
    ``list``/``List[X]``, ``dict``/``Dict[K, V]``, ``type(None)``,
    ``typing.Any``, ``typing.Optional[X]``, ``typing.Union[...]``,
    ``typing.Literal[...]`` and any other callable (``enum.Enum`` subclasses,
    ``decimal.Decimal``, ...).

    Args:
        value: Raw value, usually the string read from an environment variable,
            configuration file or secret store.
        target_type: Type or ``typing`` construct to convert ``value`` into.
        key: Optional key name, used to enrich the raised
            :class:`~smartenv.exceptions.CastError`.

    Returns:
        The converted value. ``None`` for ``Optional`` targets whose value is
        empty or one of ``"null"``, ``"none"``.

    Raises:
        CastError: If ``value`` cannot be represented as ``target_type``.

    Examples:
        >>> cast("42", int)
        42
        >>> cast("yes", bool)
        True
        >>> cast('{"a": 1}', dict)
        {'a': 1}
        >>> from typing import Literal
        >>> cast("dev", Literal["dev", "prod"])
        'dev'
    """
    if target_type is None or target_type is Any or target_type is object:
        return value

    origin = typing.get_origin(target_type)
    args = typing.get_args(target_type)

    if origin in _UNION_ORIGINS:
        return _cast_union(value, target_type, args, key)
    if origin is typing.Literal:
        return _cast_literal(value, target_type, args, key)
    if origin is list or target_type is list or target_type is typing.List:
        return _cast_list(value, target_type, args, key)
    if origin is dict or target_type is dict or target_type is typing.Dict:
        return _cast_dict(value, target_type, args, key)
    if target_type is str:
        return value if isinstance(value, str) else str(value)
    if target_type is bytes:
        return _cast_bytes(value, target_type, key)
    if target_type is bool:
        return _cast_bool(value, target_type, key)
    if target_type is int:
        return _cast_number(value, target_type, int, key)
    if target_type is float:
        return _cast_number(value, target_type, float, key)
    if target_type is type(None):
        return _cast_none(value, target_type, key)
    return _cast_callable(value, target_type, key)


def can_cast(value: Any, target_type: Any) -> bool:
    """Report whether :func:`cast` can convert ``value`` to ``target_type``.

    Args:
        value: Raw value to test.
        target_type: Type or ``typing`` construct to test against.

    Returns:
        ``True`` when the conversion succeeds, ``False`` when it raises
        :class:`~smartenv.exceptions.CastError`.
    """
    try:
        cast(value, target_type)
    except CastError:
        return False
    return True


def _name(target: Any) -> str:
    """Return a short display name for a cast target.

    Args:
        target: A type, ``typing`` construct or callable.

    Returns:
        The bare class name for classes, otherwise ``str(target)``.
    """
    if isinstance(target, type):
        return target.__name__
    return str(target)


def _is_none_like(value: Any) -> bool:
    """Report whether ``value`` should be treated as "not set".

    Args:
        value: Raw value to inspect.

    Returns:
        ``True`` for ``None`` and for the strings ``""``, ``"null"`` and
        ``"none"`` (case insensitive, surrounding whitespace ignored).
    """
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() in _NONE_VALUES
    return False


def _cast_none(value: Any, target_type: Any, key: str) -> None:
    """Cast ``value`` to ``NoneType``.

    Args:
        value: Raw value; only ``None`` or a "none like" string is accepted.
        target_type: The requested target, used for error reporting.
        key: Optional key name used to enrich the raised error.

    Returns:
        ``None``.

    Raises:
        CastError: If ``value`` is not "none like".
    """
    if _is_none_like(value):
        return None
    raise CastError(value, target_type, key=key, reason="expected one of: '', 'null', 'none'")


def _cast_bool(value: Any, target_type: Any, key: str) -> bool:
    """Cast ``value`` to ``bool``.

    Args:
        value: Raw value. Strings are matched case insensitively against
            :data:`TRUE_VALUES` and :data:`FALSE_VALUES`.
        target_type: The requested target, used for error reporting.
        key: Optional key name used to enrich the raised error.

    Returns:
        The parsed boolean.

    Raises:
        CastError: If a string is not a recognised boolean literal.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in TRUE_VALUES:
            return True
        if normalized in FALSE_VALUES:
            return False
        accepted = ", ".join(TRUE_VALUES + FALSE_VALUES)
        raise CastError(value, target_type, key=key, reason=f"expected one of: {accepted}")
    if isinstance(value, (int, float)):
        return bool(value)
    raise CastError(value, target_type, key=key, reason="expected a boolean string")


def _cast_number(value: Any, target_type: Any, converter: Callable[[Any], Any], key: str) -> Any:
    """Cast ``value`` with ``int`` or ``float``.

    Args:
        value: Raw value passed to ``converter``.
        target_type: The requested target, used for error reporting.
        converter: ``int`` or ``float``.
        key: Optional key name used to enrich the raised error.

    Returns:
        The numeric value produced by ``converter``.

    Raises:
        CastError: If ``converter`` rejects ``value``.
    """
    try:
        return converter(value)
    except (TypeError, ValueError) as exc:
        raise CastError(value, target_type, key=key, reason=str(exc)) from exc


def _cast_bytes(value: Any, target_type: Any, key: str) -> bytes:
    """Cast ``value`` to ``bytes`` using UTF-8.

    Args:
        value: ``str``, ``bytes``, ``bytearray`` or any object accepted by ``bytes``.
        target_type: The requested target, used for error reporting.
        key: Optional key name used to enrich the raised error.

    Returns:
        The UTF-8 encoded bytes.

    Raises:
        CastError: If ``value`` cannot be encoded.
    """
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return bytes(value, "utf-8")
    if isinstance(value, bytearray):
        return bytes(value)
    try:
        return bytes(value)
    except (TypeError, ValueError) as exc:
        raise CastError(value, target_type, key=key, reason=str(exc)) from exc


def _parse_json_array(text: str, target_type: Any, key: str) -> List[Any]:
    """Parse ``text`` as a JSON array.

    Args:
        text: Text starting with ``"["``.
        target_type: The requested target, used for error reporting.
        key: Optional key name used to enrich the raised error.

    Returns:
        The decoded list.

    Raises:
        CastError: If ``text`` is not valid JSON or not a JSON array.
    """
    try:
        parsed = json.loads(text)
    except ValueError as exc:
        reason = f"invalid JSON array: {exc}"
        raise CastError(text, target_type, key=key, reason=reason) from exc
    if isinstance(parsed, list):
        return parsed
    raise CastError(text, target_type, key=key, reason="JSON value is not an array")


def _cast_list(value: Any, target_type: Any, args: Tuple[Any, ...], key: str) -> List[Any]:
    """Cast ``value`` to a list.

    A JSON array is decoded when the text starts with ``"["``; any other text is
    split on commas with surrounding whitespace stripped and empty entries
    dropped. Elements are cast to the element type when the target is written as
    ``List[X]`` or ``list[X]``.

    Args:
        value: Raw value: a sequence, a JSON array, a comma separated string,
            ``None`` or an empty string.
        target_type: The requested target, used for error reporting.
        args: Type arguments of the target, e.g. ``(int,)`` for ``List[int]``.
        key: Optional key name used to enrich the raised error.

    Returns:
        A new list.

    Raises:
        CastError: If ``value`` is not list like, or an element cannot be cast.
    """
    items: List[Any] = []
    if isinstance(value, (list, tuple, set, frozenset)):
        items = list(value)
    elif value is None:
        items = []
    elif isinstance(value, str):
        text = value.strip()
        if text.startswith("["):
            items = _parse_json_array(text, target_type, key)
        elif text:
            items = [part.strip() for part in text.split(",") if part.strip()]
    else:
        raise CastError(
            value,
            target_type,
            key=key,
            reason="expected a JSON array, a comma separated string or a sequence",
        )

    if len(args) == 1 and args[0] is not Any:
        return [cast(item, args[0], key=key) for item in items]
    return items


def _cast_dict(value: Any, target_type: Any, args: Tuple[Any, ...], key: str) -> Dict[Any, Any]:
    """Cast ``value`` to a dict by parsing a JSON object.

    Values are cast to the value type when the target is written as
    ``Dict[str, int]`` or ``dict[str, int]``; keys are left untouched.

    Args:
        value: Raw value: a mapping, a JSON object string, ``None`` or an empty string.
        target_type: The requested target, used for error reporting.
        args: Type arguments of the target, e.g. ``(str, int)`` for ``Dict[str, int]``.
        key: Optional key name used to enrich the raised error.

    Returns:
        A new dict.

    Raises:
        CastError: If ``value`` is not a mapping or a JSON object, or a value
            cannot be cast.
    """
    result: Dict[Any, Any] = {}
    if isinstance(value, dict):
        result = dict(value)
    elif value is None:
        result = {}
    elif isinstance(value, str):
        text = value.strip()
        if text:
            try:
                parsed = json.loads(text)
            except ValueError as exc:
                reason = f"invalid JSON object: {exc}"
                raise CastError(text, target_type, key=key, reason=reason) from exc
            if not isinstance(parsed, dict):
                raise CastError(text, target_type, key=key, reason="JSON value is not an object")
            result = parsed
    else:
        raise CastError(
            value, target_type, key=key, reason="expected a JSON object string or a mapping"
        )

    if len(args) == 2 and args[1] is not Any:
        return {name: cast(item, args[1], key=key) for name, item in result.items()}
    return result


def _cast_union(value: Any, target_type: Any, args: Tuple[Any, ...], key: str) -> Any:
    """Cast ``value`` through a ``Union`` or ``Optional`` target.

    ``Optional[X]`` behaves exactly like ``X`` except that ``None``, ``""``,
    ``"null"`` and ``"none"`` produce ``None``. For a genuine union every option
    is tried in declaration order and the first success wins.

    Args:
        value: Raw value to convert.
        target_type: The requested target, used for error reporting.
        args: Type arguments of the union, e.g. ``(int, NoneType)``.
        key: Optional key name used to enrich the raised error.

    Returns:
        The converted value, or ``None`` for an optional target with an empty value.

    Raises:
        CastError: If no union member accepts ``value``.
    """
    options = tuple(arg for arg in args if arg is not type(None))
    allows_none = len(options) != len(args)

    if allows_none and _is_none_like(value):
        return None
    if len(options) == 1:
        return cast(value, options[0], key=key)

    for option in options:
        try:
            return cast(value, option, key=key)
        except CastError:
            continue

    candidates = ", ".join(_name(option) for option in options)
    raise CastError(value, target_type, key=key, reason=f"value matches none of: {candidates}")


def _cast_literal(value: Any, target_type: Any, args: Tuple[Any, ...], key: str) -> Any:
    """Cast ``value`` to one of the values allowed by a ``Literal`` target.

    Environment values always arrive as text, so ``Literal[1, 2]`` accepts
    ``"2"`` and ``Literal[True, False]`` accepts ``"true"``.

    Args:
        value: Raw value to convert.
        target_type: The requested target, used for error reporting.
        args: The allowed literal values, e.g. ``("dev", "prod")``.
        key: Optional key name used to enrich the raised error.

    Returns:
        The matching literal argument.

    Raises:
        CastError: If ``value`` matches none of the allowed values.
    """
    for option in args:
        if value is option or value == option:
            return option
        if isinstance(value, str):
            text = value.strip()
            if isinstance(option, str):
                if text == option:
                    return option
            elif option is None:
                if text.lower() in _NONE_VALUES:
                    return None
            else:
                try:
                    if cast(text, type(option), key=key) == option:
                        return option
                except CastError:
                    continue

    allowed = ", ".join(repr(option) for option in args)
    raise CastError(value, target_type, key=key, reason=f"expected one of: {allowed}")


def _cast_callable(value: Any, target_type: Any, key: str) -> Any:
    """Cast ``value`` by calling ``target_type`` as a constructor.

    This handles target types that are not built into :func:`cast`, such as
    ``enum.Enum`` subclasses, ``decimal.Decimal`` or user defined types.

    Args:
        value: Raw value passed to the constructor.
        target_type: A class or any other callable.
        key: Optional key name used to enrich the raised error.

    Returns:
        The constructed object, or ``value`` unchanged when it already is an
        instance of ``target_type``.

    Raises:
        CastError: If ``target_type`` is not callable or the call fails.
    """
    if isinstance(target_type, type) and isinstance(value, target_type):
        return value
    if not callable(target_type):
        raise CastError(
            value, target_type, key=key, reason="target is neither a known type nor callable"
        )
    try:
        return target_type(value)
    except (TypeError, ValueError) as exc:
        raise CastError(value, target_type, key=key, reason=str(exc)) from exc
