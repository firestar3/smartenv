"""Schema helpers for smartenv.

A *schema* declares the type of every key smartenv exposes. Schemas are normally
plain mappings of key to type, but pydantic models can be passed directly so the
validation rules are declared once::

    from typing import Optional

    from smartenv import Env

    env = Env({"PORT": int, "DEBUG": Optional[bool]}, sources=["os", ".env"])

pydantic stays optional: models are recognised through their ``model_fields``
(pydantic v2) or ``__fields__`` (pydantic v1) attributes, so pydantic is never
imported by smartenv itself.

Example:
    >>> normalize_schema({"PORT": int})["PORT"]
    <class 'int'>
    >>> get_default_value(bool)
    'false'
"""

from __future__ import annotations

import enum
import types
import typing
from typing import Any, Dict, Mapping, Optional, Tuple

__all__ = ["get_default_value", "normalize_schema"]

_UNION_ORIGINS: Tuple[Any, ...] = (typing.Union,)
_union_type = getattr(types, "UnionType", None)
if _union_type is not None:  # Python 3.10+ writes unions as ``int | None``.
    _UNION_ORIGINS = (typing.Union, _union_type)

_SEQUENCE_TYPES: Tuple[Any, ...] = (list, set, frozenset, tuple)
"""Container types whose placeholder is an empty JSON array."""


def normalize_schema(schema: Any) -> Dict[str, Any]:
    """Turn a schema declaration into a mapping of key to type hint.

    Args:
        schema: A mapping of key to type or ``typing`` construct, e.g.
            ``{"PORT": int, "TAGS": List[str]}``; or a pydantic model class, whose
            field annotations are used as the schema.

    Returns:
        A new dictionary of key to type hint, in declaration order.

    Raises:
        TypeError: If ``schema`` is neither a mapping, nor a key to type mapping,
            nor a pydantic (v1 or v2) model class.

    Example:
        >>> normalize_schema({"PORT": int})["PORT"]
        <class 'int'>
    """
    if isinstance(schema, Mapping):
        normalized: Dict[str, Any] = {}
        for key, type_hint in schema.items():
            if not isinstance(key, str) or not key:
                raise TypeError(f"schema keys must be non-empty strings, got {key!r}")
            normalized[key] = type_hint
        return normalized

    if isinstance(schema, type):
        fields = _extract_model_fields(schema)
        if fields is not None:
            return fields

    described = schema.__name__ if isinstance(schema, type) else type(schema).__name__
    raise TypeError(
        f"schema must be a mapping of key to type or a pydantic model class, got {described!r}; "
        "pydantic models need the optional dependency (pip install smartenv[pydantic])"
    )


def get_default_value(type_hint: Any) -> str:
    """Return a placeholder value for ``type_hint``.

    The placeholder is always a value the type accepts, which makes it suitable
    for generated ``.env.example`` templates::

        PORT=0          # int
        DEBUG=false     # bool
        TAGS=[]         # List[str]
        MODE=dev        # Literal["dev", "prod"]

    ``Optional[X]`` falls back to the placeholder of ``X``, enums use their first
    member, and anything unknown yields an empty string.

    Args:
        type_hint: Type or ``typing`` construct declared in a schema.

    Returns:
        The placeholder text.

    Example:
        >>> get_default_value(int)
        '0'
        >>> get_default_value(typing.List[str])
        '[]'
    """
    if type_hint is None or type_hint is Any or type_hint is object:
        return ""
    if type_hint is type(None):
        return ""
    if isinstance(type_hint, type) and issubclass(type_hint, enum.Enum):
        members = list(type_hint)
        return _text_of(members[0].value) if members else ""

    origin = typing.get_origin(type_hint)
    args = typing.get_args(type_hint)

    if origin in _UNION_ORIGINS:
        members = [member for member in args if member is not type(None)]
        return get_default_value(members[0]) if members else ""
    if origin is typing.Literal:
        return _text_of(args[0]) if args else ""
    if origin in _SEQUENCE_TYPES or type_hint in _SEQUENCE_TYPES:
        return "[]"
    if origin is dict or type_hint is dict:
        return "{}"
    if type_hint is bool:
        return "false"
    if type_hint is int:
        return "0"
    if type_hint is float:
        return "0.0"
    return ""


def _extract_model_fields(model: type) -> Optional[Dict[str, Any]]:
    """Extract field annotations from a pydantic model class.

    Detection is duck typed, so pydantic never has to be imported: pydantic v2
    exposes ``model_fields`` and pydantic v1 exposes ``__fields__``.

    Args:
        model: Candidate model class.

    Returns:
        ``{field_name: annotation}`` for model classes, otherwise ``None``.
    """
    fields = getattr(model, "model_fields", None)  # pydantic v2
    if isinstance(fields, Mapping):
        return {str(name): _field_annotation(info) for name, info in fields.items()}

    fields = getattr(model, "__fields__", None)  # pydantic v1
    if isinstance(fields, Mapping):
        return {str(name): _field_annotation(info) for name, info in fields.items()}

    return None


def _field_annotation(field: Any) -> Any:
    """Return the annotated type of a pydantic field.

    Args:
        field: A pydantic ``FieldInfo`` (v1 or v2).

    Returns:
        The annotation, preferring the outer type when the field is optional, and
        ``typing.Any`` when nothing usable is exposed.
    """
    annotation = getattr(field, "outer_type_", None)
    if annotation is None:
        annotation = getattr(field, "annotation", None)
    return Any if annotation is None else annotation


def _text_of(value: Any) -> str:
    """Return the string form of a literal or enum value.

    Args:
        value: A literal or enum member value.

    Returns:
        ``"true"``/``"false"`` for booleans, ``""`` for ``None``, the value itself
        for strings, UTF-8 text for bytes and ``str(value)`` otherwise.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)
