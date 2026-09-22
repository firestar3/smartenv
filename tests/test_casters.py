"""Tests for :mod:`smartenv.casters`."""

from __future__ import annotations

import enum
from typing import Any, Dict, List, Literal, Optional, Union

import pytest

from smartenv.casters import FALSE_VALUES, TRUE_VALUES, can_cast, cast
from smartenv.exceptions import CastError


class Mode(enum.Enum):
    """Sample enum used to exercise the generic callable fallback."""

    DEV = "dev"
    PROD = "prod"


# --- str ---------------------------------------------------------------------


def test_cast_str_passthrough() -> None:
    assert cast("hello", str) == "hello"


def test_cast_str_keeps_unicode() -> None:
    assert cast("héllo ✓", str) == "héllo ✓"


def test_cast_str_from_non_string() -> None:
    assert cast(42, str) == "42"


# --- int ---------------------------------------------------------------------


def test_cast_int_from_string() -> None:
    result = cast("42", int)
    assert result == 42
    assert isinstance(result, int)


def test_cast_int_negative_and_zero() -> None:
    assert cast("-7", int) == -7
    assert cast("0", int) == 0


def test_cast_int_invalid_raises_cast_error() -> None:
    with pytest.raises(CastError) as exc_info:
        cast("abc", int)

    error = exc_info.value
    assert error.value == "abc"
    assert error.target_type is int
    assert "cannot cast" in str(error)
    assert error.reason


def test_cast_int_float_text_raises() -> None:
    with pytest.raises(CastError):
        cast("3.5", int)


# --- float -------------------------------------------------------------------


def test_cast_float_from_string() -> None:
    assert cast("3.14", float) == pytest.approx(3.14)


def test_cast_float_scientific_notation() -> None:
    assert cast("1e3", float) == pytest.approx(1000.0)


def test_cast_float_invalid_raises_cast_error() -> None:
    with pytest.raises(CastError) as exc_info:
        cast("not-a-number", float)

    assert exc_info.value.value == "not-a-number"
    assert exc_info.value.target_type is float


# --- bool --------------------------------------------------------------------


@pytest.mark.parametrize("raw", ["true", "TRUE", "True", "1", "yes", "YES", "on", "ON", " on "])
def test_cast_bool_truthy_strings(raw: str) -> None:
    assert cast(raw, bool) is True


@pytest.mark.parametrize("raw", ["false", "FALSE", "False", "0", "no", "NO", "off", "OFF", " off "])
def test_cast_bool_falsy_strings(raw: str) -> None:
    assert cast(raw, bool) is False


def test_cast_bool_invalid_raises_cast_error() -> None:
    with pytest.raises(CastError) as exc_info:
        cast("maybe", bool)

    error = exc_info.value
    assert error.value == "maybe"
    assert error.target_type is bool
    assert "true" in error.reason and "false" in error.reason


def test_cast_bool_empty_string_raises() -> None:
    with pytest.raises(CastError):
        cast("", bool)


def test_cast_bool_accepts_real_bool() -> None:
    assert cast(True, bool) is True
    assert cast(False, bool) is False


def test_bool_value_sets_are_disjoint_and_complete() -> None:
    assert not set(TRUE_VALUES) & set(FALSE_VALUES)
    assert set(TRUE_VALUES) == {"true", "1", "yes", "on"}
    assert set(FALSE_VALUES) == {"false", "0", "no", "off"}


# --- list --------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("a,b,c", ["a", "b", "c"]),
        ("a, b , c", ["a", "b", "c"]),
        ("single", ["single"]),
        ("a,,b", ["a", "b"]),
        ("", []),
    ],
)
def test_cast_list_from_comma_separated(raw: str, expected: List[str]) -> None:
    assert cast(raw, List[str]) == expected


def test_cast_list_with_bare_list_type() -> None:
    result = cast("a,b", list)
    assert result == ["a", "b"]
    assert isinstance(result, list)


def test_cast_list_from_json_array() -> None:
    assert cast('["x", "y"]', List[str]) == ["x", "y"]


def test_cast_list_from_json_array_of_numbers() -> None:
    assert cast("[1, 2, 3]", List[int]) == [1, 2, 3]


def test_cast_list_of_ints_from_comma_separated() -> None:
    assert cast("1,2,3", List[int]) == [1, 2, 3]


def test_cast_list_from_python_sequence() -> None:
    assert cast(("a", "b"), List[str]) == ["a", "b"]


def test_cast_list_element_failure_names_offending_value() -> None:
    with pytest.raises(CastError) as exc_info:
        cast("1,x", List[int])

    assert exc_info.value.value == "x"
    assert exc_info.value.target_type is int


def test_cast_list_malformed_json_raises() -> None:
    with pytest.raises(CastError) as exc_info:
        cast("[1, 2", List[int])

    assert "JSON" in exc_info.value.reason


# --- dict --------------------------------------------------------------------


def test_cast_dict_from_json_object() -> None:
    assert cast('{"a": 1}', Dict[str, int]) == {"a": 1}


def test_cast_dict_from_json_nested() -> None:
    assert cast('{"a": {"b": 2}}', dict) == {"a": {"b": 2}}


def test_cast_dict_with_bare_dict_type() -> None:
    assert cast('{"a": "b"}', dict) == {"a": "b"}


def test_cast_dict_empty_string_is_empty_dict() -> None:
    assert cast("", dict) == {}


def test_cast_dict_casts_values() -> None:
    assert cast('{"a": "1", "b": "2"}', Dict[str, int]) == {"a": 1, "b": 2}


def test_cast_dict_from_mapping() -> None:
    assert cast({"a": "1"}, Dict[str, int]) == {"a": 1}


def test_cast_dict_invalid_json_raises() -> None:
    with pytest.raises(CastError) as exc_info:
        cast("not json", dict)

    assert "JSON" in exc_info.value.reason


def test_cast_dict_json_array_raises() -> None:
    with pytest.raises(CastError) as exc_info:
        cast('["a"]', dict)

    assert "not an object" in exc_info.value.reason


def test_cast_dict_value_failure_raises() -> None:
    with pytest.raises(CastError) as exc_info:
        cast('{"a": "x"}', Dict[str, int])

    assert exc_info.value.value == "x"


# --- Optional / Union --------------------------------------------------------


@pytest.mark.parametrize("raw", ["", "null", "NULL", "none", "None", " None "])
def test_cast_optional_none_like_values(raw: str) -> None:
    assert cast(raw, Optional[int]) is None


def test_cast_optional_accepts_none_object() -> None:
    assert cast(None, Optional[str]) is None


def test_cast_optional_present_value() -> None:
    assert cast("42", Optional[int]) == 42


def test_cast_optional_bool_value() -> None:
    assert cast("true", Optional[bool]) is True


def test_cast_optional_invalid_value_raises() -> None:
    with pytest.raises(CastError) as exc_info:
        cast("abc", Optional[int])

    assert exc_info.value.value == "abc"
    assert exc_info.value.target_type is int


def test_cast_union_prefers_first_matching_member() -> None:
    assert cast("42", Union[int, str]) == 42


def test_cast_union_falls_back_to_later_member() -> None:
    assert cast("abc", Union[int, str]) == "abc"


def test_cast_union_with_no_matching_member_raises() -> None:
    with pytest.raises(CastError) as exc_info:
        cast("abc", Union[int, float])

    assert "matches none of" in exc_info.value.reason


# --- Literal -----------------------------------------------------------------


def test_cast_literal_valid_value() -> None:
    assert cast("dev", Literal["dev", "prod"]) == "dev"


def test_cast_literal_invalid_value_raises() -> None:
    with pytest.raises(CastError) as exc_info:
        cast("staging", Literal["dev", "prod"])

    error = exc_info.value
    assert error.value == "staging"
    assert "dev" in error.reason and "prod" in error.reason


def test_cast_literal_int_value_from_text() -> None:
    assert cast("2", Literal[1, 2, 3]) == 2


def test_cast_literal_bool_value_from_text() -> None:
    assert cast("true", Literal[True, False]) is True


def test_cast_literal_none_member() -> None:
    assert cast("null", Literal["debug", None]) is None


# --- None, Any and generic fallbacks ----------------------------------------


def test_cast_none_type_accepts_none_like() -> None:
    assert cast("null", type(None)) is None


def test_cast_none_type_rejects_other_values() -> None:
    with pytest.raises(CastError):
        cast("something", type(None))


def test_cast_any_returns_value_unchanged() -> None:
    assert cast("raw", Any) == "raw"


def test_cast_enum_fallback() -> None:
    assert cast("dev", Mode) is Mode.DEV


def test_cast_already_typed_value_is_returned() -> None:
    assert cast(7, int) == 7
    assert cast(Mode.PROD, Mode) is Mode.PROD


def test_cast_unknown_non_callable_target_raises() -> None:
    with pytest.raises(CastError):
        cast("x", 42)


# --- error context and helpers ----------------------------------------------


def test_cast_error_includes_key_context() -> None:
    with pytest.raises(CastError) as exc_info:
        cast("abc", int, key="PORT")

    error = exc_info.value
    assert error.key == "PORT"
    assert "PORT" in str(error)
    assert error.value == "abc"


def test_cast_error_without_key_has_empty_key() -> None:
    with pytest.raises(CastError) as exc_info:
        cast("abc", int)

    assert exc_info.value.key == ""


def test_can_cast_reports_success_and_failure() -> None:
    assert can_cast("42", int) is True
    assert can_cast("abc", int) is False
    assert can_cast("null", Optional[int]) is True
