"""Tests for :mod:`smartenv.validators`."""

from __future__ import annotations

from typing import Any, List, Optional

import pytest

from smartenv.exceptions import ValidationError
from smartenv.validators import ValidationResult, validate, validate_or_raise


def test_all_present_and_valid_produces_clean_result() -> None:
    env = {"HOST": "localhost", "PORT": "8080", "DEBUG": "yes"}
    schema = {"HOST": str, "PORT": int, "DEBUG": bool}

    result = validate(env, schema, ["HOST", "PORT"])

    assert result.is_valid is True
    assert result.errors == []
    assert result.warnings == []
    assert bool(result) is True


def test_missing_required_key_is_reported() -> None:
    result = validate({"HOST": "localhost"}, {}, ["HOST", "API_KEY"])

    assert result.is_valid is False
    assert bool(result) is False
    assert any("API_KEY" in error for error in result.errors)
    assert any("missing required key" in error for error in result.errors)


def test_missing_required_key_with_schema_is_reported() -> None:
    result = validate({}, {"PORT": int}, ["PORT"])

    assert result.is_valid is False
    assert len(result.errors) == 1
    assert "PORT" in result.errors[0]


def test_wrong_type_value_is_reported() -> None:
    result = validate({"PORT": "abc"}, {"PORT": int}, ["PORT"])

    assert result.is_valid is False
    assert result.errors
    assert all("PORT" in error for error in result.errors)
    assert "cannot cast" in result.errors[0]
    assert "abc" in result.errors[0]


def test_custom_validator_passes() -> None:
    result = validate(
        {"TIMEOUT": "30"},
        {"TIMEOUT": int},
        ["TIMEOUT"],
        {"TIMEOUT": lambda value: value >= 1},
    )

    assert result.is_valid is True
    assert result.errors == []


def test_custom_validator_receives_cast_value() -> None:
    seen: List[Any] = []

    def record(value: Any) -> bool:
        seen.append(value)
        return True

    validate({"PORT": "8080"}, {"PORT": int}, ["PORT"], {"PORT": record})

    assert seen == [8080]
    assert isinstance(seen[0], int)


def test_custom_validator_returning_error_string_fails() -> None:
    message = "TIMEOUT must be at least 1024"
    result = validate(
        {"TIMEOUT": "10"},
        {"TIMEOUT": int},
        ["TIMEOUT"],
        {"TIMEOUT": lambda value: message},
    )

    assert result.is_valid is False
    assert message in result.errors


def test_custom_validator_returning_false_fails() -> None:
    result = validate(
        {"TIMEOUT": "10"},
        {"TIMEOUT": int},
        ["TIMEOUT"],
        {"TIMEOUT": lambda value: False},
    )

    assert result.is_valid is False
    assert any("TIMEOUT" in error and "failed" in error for error in result.errors)


def test_custom_validator_returning_none_passes() -> None:
    result = validate(
        {"HOST": "localhost"},
        {"HOST": str},
        ["HOST"],
        {"HOST": lambda value: None},
    )

    assert result.is_valid is True


def test_custom_validator_that_raises_is_reported() -> None:
    def explode(value: Any) -> bool:
        raise ValueError("boom")

    result = validate({"PORT": "8080"}, {"PORT": int}, ["PORT"], {"PORT": explode})

    assert result.is_valid is False
    assert any("ValueError" in error and "boom" in error for error in result.errors)


def test_custom_validator_is_not_run_when_cast_fails() -> None:
    calls: List[Any] = []

    def never(value: Any) -> bool:
        calls.append(value)
        return True

    result = validate({"PORT": "abc"}, {"PORT": int}, ["PORT"], {"PORT": never})

    assert result.is_valid is False
    assert calls == []


def test_custom_validator_runs_without_schema_entry() -> None:
    seen: List[Any] = []

    def record(value: Any) -> bool:
        seen.append(value)
        return True

    result = validate({"MODE": "dev"}, {}, [], {"MODE": record})

    assert result.is_valid is True
    assert seen == ["dev"]


def test_empty_required_value_is_error() -> None:
    result = validate({"API_KEY": ""}, {}, ["API_KEY"])

    assert result.is_valid is False
    assert any("API_KEY" in error and "empty" in error for error in result.errors)


def test_whitespace_only_required_value_is_error() -> None:
    result = validate({"API_KEY": "   "}, {"API_KEY": str}, ["API_KEY"])

    assert result.is_valid is False
    assert any("empty" in error for error in result.errors)


def test_none_required_value_is_error() -> None:
    result = validate({"API_KEY": None}, {}, ["API_KEY"])

    assert result.is_valid is False
    assert any("empty" in error for error in result.errors)


def test_empty_optional_value_is_skipped() -> None:
    result = validate({"DEBUG": ""}, {"DEBUG": Optional[bool]}, [])

    assert result.is_valid is True
    assert result.errors == []


def test_declared_optional_key_missing_is_not_an_error() -> None:
    result = validate({"HOST": "localhost"}, {"HOST": str, "PORT": Optional[int]}, ["HOST"])

    assert result.is_valid is True
    assert result.errors == []


def test_result_reports_every_problem_at_once() -> None:
    env = {"PORT": "abc", "TIMEOUT": "0", "HOST": ""}
    schema = {"PORT": int, "TIMEOUT": int, "HOST": str}

    result = validate(
        env, schema, ["PORT", "HOST", "SECRET"], {"TIMEOUT": lambda value: "TIMEOUT too small"}
    )

    assert result.is_valid is False
    assert len(result.errors) == 4
    assert any("missing required key 'SECRET'" in error for error in result.errors)
    assert any("TIMEOUT too small" in error for error in result.errors)


def test_validator_for_unset_key_warns() -> None:
    result = validate({}, {"PORT": Optional[int]}, [], {"PORT": lambda value: True})

    assert result.is_valid is True
    assert any("PORT" in warning and "skipped" in warning for warning in result.warnings)


def test_required_key_without_schema_warns() -> None:
    result = validate({"API_KEY": "secret"}, {}, ["API_KEY"])

    assert result.is_valid is True
    assert result.errors == []
    assert any("API_KEY" in warning for warning in result.warnings)


def test_duplicate_required_keys_are_reported_once() -> None:
    result = validate({}, {"PORT": int}, ["PORT", "PORT"])

    assert len(result.errors) == 1


def test_validate_never_raises_on_uncastable_schema() -> None:
    result = validate({"X": "1"}, {"X": 42}, [])

    assert result.is_valid is False
    assert result.errors


def test_validation_result_raise_if_invalid() -> None:
    result = validate({"PORT": "abc"}, {"PORT": int}, ["PORT"])

    with pytest.raises(ValidationError) as exc_info:
        result.raise_if_invalid()

    error = exc_info.value
    assert error.errors == result.errors
    assert error.warnings == result.warnings
    assert "cannot cast" in str(error)
    assert "PORT" in str(error)


def test_validation_result_raise_if_invalid_is_noop_when_valid() -> None:
    result = validate({"PORT": "8080"}, {"PORT": int}, ["PORT"])

    result.raise_if_invalid()
    assert result.is_valid is True


def test_validate_or_raise_returns_result_when_valid() -> None:
    result = validate_or_raise({"PORT": "8080"}, {"PORT": int}, ["PORT"])

    assert isinstance(result, ValidationResult)
    assert result.is_valid is True


def test_validate_or_raise_raises_validation_error() -> None:
    with pytest.raises(ValidationError) as exc_info:
        validate_or_raise({"PORT": "abc"}, {"PORT": int}, ["PORT"])

    assert exc_info.value.errors
