"""Regression coverage for secret-safe configuration diagnostics."""

from __future__ import annotations

from typing import Any

import pytest

from smartenv import Env
from smartenv.casters import cast
from smartenv.exceptions import CastError, ValidationError
from smartenv.security import is_sensitive_key, mask_value
from smartenv.validators import validate


@pytest.mark.parametrize(
    "key",
    [
        "SECRET",
        "api_key",
        "ACCESS_TOKEN",
        "PASSWORD",
        "db_pass",
        "CREDENTIAL",
        "AUTH",
        "PRIVATE",
        "CERT",
    ],
)
def test_sensitive_keys_share_one_case_insensitive_masking_rule(key: str) -> None:
    assert is_sensitive_key(key)
    assert mask_value(key, "private") == "***"
    assert mask_value(key, "private", mask="*****") == "*****"


def test_ordinary_keys_keep_their_values() -> None:
    assert not is_sensitive_key("PORT")
    assert mask_value("PORT", 8080) == 8080


def test_sensitive_cast_error_masks_value_and_underlying_reason() -> None:
    with pytest.raises(CastError) as exc_info:
        cast("private-value", int, key="API_SECRET")

    error = exc_info.value
    assert error.value == "private-value"
    assert "private-value" in error.reason
    assert "private-value" not in str(error)
    assert "private-value" not in repr(error)
    assert "private-value" not in str(error.args)
    assert "API_SECRET" in str(error)


@pytest.mark.parametrize("kind", ["message", "exception", "invalid_return"])
def test_sensitive_custom_validator_diagnostics_never_include_values(kind: str) -> None:
    def validator(value: Any) -> Any:
        if kind == "exception":
            raise ValueError(f"rejected {value}")
        if kind == "invalid_return":
            return {"rejected": value}
        return f"rejected {value}"

    result = validate(
        {"TOKEN": "private-value"}, {"TOKEN": str}, custom_validators={"TOKEN": validator}
    )

    assert not result.is_valid
    assert "TOKEN" in result.errors[0]
    assert "private-value" not in str(result)
    with pytest.raises(ValidationError) as exc_info:
        result.raise_if_invalid()
    assert "private-value" not in str(exc_info.value)
    assert "private-value" not in repr(exc_info.value)


def test_sensitive_startup_validation_keeps_secret_out_of_report() -> None:
    with pytest.raises(ValidationError) as exc_info:
        Env({"API_KEY": int}, sources=[], defaults={"API_KEY": "private-value"}, strict=True)

    assert "private-value" not in str(exc_info.value)
    assert "API_KEY" in str(exc_info.value)
