"""Schema validation for smartenv.

:func:`validate` compares a dictionary of resolved key/value pairs with a schema
and a list of required keys, then reports *everything* it found instead of
failing on the first problem. Nothing ever raises: the caller decides whether to
log the report, raise :class:`~smartenv.exceptions.ValidationError` or ignore it.

Example:
    >>> from typing import Optional
    >>> schema = {"PORT": int, "DEBUG": Optional[bool]}
    >>> result = validate({"PORT": "8080", "DEBUG": "yes"}, schema, ["PORT"])
    >>> result.is_valid
    True
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Union

from smartenv.casters import cast
from smartenv.exceptions import CastError, ValidationError

__all__ = ["Validator", "ValidationResult", "validate", "validate_or_raise"]

Validator = Callable[[Any], Union[bool, None, str]]
"""Custom validator signature.

A validator receives the *cast* value and returns ``True`` (or ``None``) when the
value is acceptable, or an error string describing the problem.
"""


@dataclass
class ValidationResult:
    """Outcome of a :func:`validate` call.

    Attributes:
        is_valid: ``True`` when no error was found.
        errors: Human readable errors, in the order they were discovered.
        warnings: Non fatal findings, e.g. a validator that could not run.
    """

    is_valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        """Allow ``if result: ...`` checks.

        Returns:
            Same as :attr:`is_valid`.
        """
        return self.is_valid

    def raise_if_invalid(self) -> None:
        """Raise :class:`~smartenv.exceptions.ValidationError` when invalid.

        Returns:
            ``None`` when the result is valid.

        Raises:
            ValidationError: If :attr:`is_valid` is ``False``, carrying
                :attr:`errors` and :attr:`warnings`.
        """
        if not self.is_valid:
            raise ValidationError(errors=self.errors, warnings=self.warnings)


def validate(
    env_dict: Mapping[str, Any],
    schema: Optional[Mapping[str, Any]] = None,
    required: Optional[Sequence[str]] = None,
    custom_validators: Optional[Mapping[str, Validator]] = None,
) -> ValidationResult:
    """Validate ``env_dict`` against ``schema`` and ``required``.

    The check never raises; every problem is collected in the returned
    :class:`ValidationResult` so the caller can decide how to react.

    Rules:
        * every key listed in ``required`` must be present and non empty;
        * every value declared in ``schema`` must cast to its declared type;
        * custom validators receive the *cast* value (not the raw string) and may
          return ``True``/``None`` for success or an error string for failure;
        * empty optional values are treated as "not set" and are not cast;
        * casting is reported with the key name attached, e.g.
          ``"key 'PORT': cannot cast 'abc' to int"``.

    Args:
        env_dict: Resolved key/value pairs, typically strings.
        schema: Mapping of key to target type, e.g. ``{"PORT": int}``. Pass
            ``None`` or ``{}`` to check presence only.
        required: Keys that must be present and non empty.
        custom_validators: Mapping of key to a callable taking the cast value.

    Returns:
        A :class:`ValidationResult` carrying ``is_valid``, ``errors`` and
        ``warnings``.

    Example:
        >>> result = validate({"PORT": "8080"}, {"PORT": int}, ["PORT"])
        >>> result.is_valid
        True
        >>> result.errors
        []
        >>> len(validate({"PORT": "abc"}, {"PORT": int}, ["PORT"]).errors)
        1
    """
    schema_map: Dict[str, Any] = dict(schema or {})
    validator_map: Dict[str, Validator] = dict(custom_validators or {})
    required_keys: List[str] = list(dict.fromkeys(required or []))

    errors: List[str] = []
    warnings: List[str] = []
    absent_keys = [key for key in env_dict if _is_empty(env_dict[key])]

    for key in required_keys:
        if key not in env_dict:
            errors.append(f"missing required key {key!r}")
        elif key in absent_keys:
            errors.append(f"required key {key!r} is empty")
        if key not in schema_map:
            warnings.append(f"required key {key!r} has no schema entry; its type cannot be checked")

    for key, expected_type in schema_map.items():
        if key not in env_dict or key in absent_keys:
            continue
        raw_value = env_dict[key]
        try:
            coerced = cast(raw_value, expected_type, key=key)
        except CastError as exc:
            errors.append(str(exc))
            continue
        validator = validator_map.get(key)
        if validator is not None:
            _run_validator(key, coerced, validator, errors)

    for key, validator in validator_map.items():
        if key not in env_dict or key in absent_keys:
            warnings.append(f"validator for {key!r} was skipped because the key is not set")
            continue
        if key in schema_map:
            continue
        _run_validator(key, env_dict[key], validator, errors)

    result = ValidationResult(
        is_valid=not errors, errors=errors, warnings=list(dict.fromkeys(warnings))
    )
    return result


def validate_or_raise(
    env_dict: Mapping[str, Any],
    schema: Optional[Mapping[str, Any]] = None,
    required: Optional[Sequence[str]] = None,
    custom_validators: Optional[Mapping[str, Validator]] = None,
) -> ValidationResult:
    """Validate like :func:`validate` but raise on the first invalid result.

    Args:
        env_dict: Resolved key/value pairs, typically strings.
        schema: Mapping of key to target type, e.g. ``{"PORT": int}``.
        required: Keys that must be present and non empty.
        custom_validators: Mapping of key to a callable taking the cast value.

    Returns:
        The successful :class:`ValidationResult`.

    Raises:
        ValidationError: If at least one error was found, carrying every error
            and warning.
    """
    result = validate(
        env_dict=env_dict,
        schema=schema,
        required=required,
        custom_validators=custom_validators,
    )
    result.raise_if_invalid()
    return result


def _is_empty(value: Any) -> bool:
    """Report whether ``value`` counts as "not set".

    Args:
        value: Value to inspect.

    Returns:
        ``True`` for ``None`` and for strings that are empty or whitespace only.
    """
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return False


def _run_validator(key: str, value: Any, validator: Validator, errors: List[str]) -> None:
    """Run a custom validator and append an error when it fails.

    A validator passes by returning ``True`` or ``None``. Returning a string is
    treated as the error message; returning ``False`` produces a generic message.
    A validator that raises is reported as an error instead of aborting the
    validation pass.

    Args:
        key: Key the validator belongs to, used in error messages.
        value: The cast value handed to the validator.
        validator: Callable returning ``True``/``None`` or an error string.
        errors: Error list, mutated in place.
    """
    try:
        outcome = validator(value)
    except Exception as exc:  # User validators may raise anything; report, never abort.
        errors.append(f"validator for {key!r} raised {type(exc).__name__}: {exc}")
        return

    if outcome is True or outcome is None:
        return
    if isinstance(outcome, str):
        errors.append(outcome if outcome else f"validator for {key!r} failed")
        return
    if outcome is False:
        errors.append(f"validator for {key!r} failed")
        return
    errors.append(
        f"validator for {key!r} returned {outcome!r}; expected True, None or an error string"
    )
