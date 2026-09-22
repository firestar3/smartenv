"""Tests for :mod:`smartenv.core` and the schema helpers it builds on."""

from __future__ import annotations

import enum
import json
import threading
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

import pytest

from smartenv import Env
from smartenv.exceptions import (
    MissingKeyError,
    MissingSourceError,
    SourceLoadError,
    ValidationError,
)
from smartenv.schema import get_default_value, normalize_schema
from smartenv.sources import BaseSource, FileSource, OsSource


def write_file(directory: Path, file_name: str, content: str) -> Path:
    """Write ``content`` as UTF-8 and return the resulting path.

    Args:
        directory: Directory to write into, usually ``tmp_path``.
        file_name: Name of the file to create.
        content: Text to write.

    Returns:
        The path of the created file.
    """
    path = directory / file_name
    path.write_text(content, encoding="utf-8")
    return path


class MemorySource(BaseSource):
    """Source serving a fixed mapping so tests never depend on the real environment."""

    def load(self) -> Dict[str, str]:
        """Return a copy of the fixed mapping.

        Returns:
            The configured key/value pairs.
        """
        return dict(self._data)

    def __init__(self, data: Dict[str, str], name: str = "memory") -> None:
        self._name = name
        self._data = dict(data)

    @property
    def name(self) -> str:
        """Return the identifier of the source.

        Returns:
            The configured identifier, ``"memory"`` by default.
        """
        return self._name


class Mode(enum.Enum):
    """Sample enum used by the placeholder tests."""

    DEV = "dev"
    PROD = "prod"


# --- normalize_schema --------------------------------------------------------


def test_normalize_schema_accepts_a_mapping() -> None:
    schema = {"PORT": int, "DEBUG": Optional[bool]}

    assert normalize_schema(schema) == {"PORT": int, "DEBUG": Optional[bool]}


def test_normalize_schema_returns_a_copy() -> None:
    schema: Dict[str, Any] = {"PORT": int}

    normalized = normalize_schema(schema)
    normalized["EXTRA"] = str

    assert schema == {"PORT": int}


def test_normalize_schema_keeps_declaration_order() -> None:
    assert list(normalize_schema({"B": int, "A": str})) == ["B", "A"]


def test_normalize_schema_rejects_values_that_are_not_mappings() -> None:
    with pytest.raises(TypeError) as exc_info:
        normalize_schema(42)

    assert "schema must be a mapping" in str(exc_info.value)


def test_normalize_schema_rejects_plain_classes() -> None:
    with pytest.raises(TypeError):
        normalize_schema(MemorySource)


def test_normalize_schema_rejects_empty_keys() -> None:
    with pytest.raises(TypeError):
        normalize_schema({"": int})


def test_normalize_schema_extracts_pydantic_model_fields() -> None:
    pydantic = pytest.importorskip("pydantic")

    model = pydantic.create_model("Settings", port=(int, ...), host=(str, "localhost"))

    assert normalize_schema(model) == {"port": int, "host": str}


def test_normalize_schema_extracts_duck_typed_v2_fields() -> None:
    class FieldInfo:
        def __init__(self, annotation: Any) -> None:
            self.annotation = annotation

    class Model:
        model_fields = {"PORT": FieldInfo(int), "HOST": FieldInfo(str)}

    assert normalize_schema(Model) == {"PORT": int, "HOST": str}


def test_normalize_schema_extracts_duck_typed_v1_fields() -> None:
    class FieldInfo:
        outer_type_ = int

    class Model:
        __fields__ = {"PORT": FieldInfo()}

    assert normalize_schema(Model) == {"PORT": int}


# --- get_default_value -------------------------------------------------------


@pytest.mark.parametrize(
    "type_hint, expected",
    [
        (str, ""),
        (int, "0"),
        (float, "0.0"),
        (bool, "false"),
        (list, "[]"),
        (List[str], "[]"),
        (Dict[str, int], "{}"),
        (dict, "{}"),
        (Optional[bool], "false"),
        (Optional[List[int]], "[]"),
        (Literal["dev", "prod"], "dev"),
        (Literal[1, 2], "1"),
        (Literal[True, False], "true"),
        (Any, ""),
        (object, ""),
        (type(None), ""),
        (Mode, "dev"),
    ],
)
def test_get_default_value_returns_a_valid_placeholder(type_hint: Any, expected: str) -> None:
    assert get_default_value(type_hint) == expected


# --- construction and loading ------------------------------------------------


def test_default_sources_is_the_process_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SMARTENV_DEFAULT_SOURCE", "42")

    env = Env({"SMARTENV_DEFAULT_SOURCE": int})

    assert env.SMARTENV_DEFAULT_SOURCE == 42
    assert isinstance(env.sources[0], OsSource)


def test_first_source_that_defines_a_key_wins(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PORT", "1")
    path = write_file(tmp_path, ".env", "PORT=8080\n")

    env = Env({"PORT": int}, sources=["os", str(path)])

    assert env.PORT == 1


def test_file_source_listed_first_beats_the_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PORT", "1")
    path = write_file(tmp_path, ".env", "PORT=8080\n")

    env = Env({"PORT": int}, sources=[str(path), "os"])

    assert env.PORT == 8080


def test_later_sources_fill_the_gaps_without_overriding(tmp_path: Path) -> None:
    path = write_file(tmp_path, ".env", "HOST=file-host\nPORT=8080\n")

    env = Env(
        {"HOST": str, "PORT": int},
        sources=[MemorySource({"HOST": "memory-host"}), str(path)],
    )

    assert env.HOST == "memory-host"
    assert env.PORT == 8080


def test_values_are_cast_to_the_declared_types(tmp_path: Path) -> None:
    path = write_file(tmp_path, ".env", "PORT=8080\nDEBUG=true\nRATIO=0.5\nHOSTS=a,b\nMODE=dev\n")

    env = Env(
        {
            "PORT": int,
            "DEBUG": bool,
            "RATIO": float,
            "HOSTS": List[str],
            "MODE": Literal["dev", "prod"],
        },
        sources=[str(path)],
    )

    assert env.PORT == 8080
    assert env.DEBUG is True
    assert pytest.approx(0.5) == env.RATIO
    assert env.HOSTS == ["a", "b"]
    assert env.MODE == "dev"


def test_json_source_keys_are_flattened(tmp_path: Path) -> None:
    path = write_file(tmp_path, "config.json", '{"database": {"host": "db", "port": 5432}}')

    env = Env({"DATABASE__HOST": str, "DATABASE__PORT": int}, sources=[str(path)])

    assert env.DATABASE__HOST == "db"
    assert env.DATABASE__PORT == 5432


def test_undeclared_keys_are_not_exposed(tmp_path: Path) -> None:
    path = write_file(tmp_path, ".env", "PORT=8080\nEXTRA=ignored\n")

    env = Env({"PORT": int}, sources=[str(path)])

    assert "EXTRA" not in env
    assert env.dict() == {"PORT": 8080}


def test_empty_optional_value_resolves_to_none(tmp_path: Path) -> None:
    path = write_file(tmp_path, ".env", "DEBUG=\n")

    env = Env({"DEBUG": Optional[bool]}, sources=[str(path)])

    assert "DEBUG" in env
    assert env.DEBUG is None


def test_empty_required_value_is_unavailable_and_reported(tmp_path: Path) -> None:
    path = write_file(tmp_path, ".env", "API_KEY=\n")

    env = Env({"API_KEY": str}, sources=[str(path)], required=["API_KEY"])

    assert "API_KEY" not in env
    assert env.valid is False
    assert any("empty" in message for message in env.errors)


def test_custom_source_objects_are_accepted() -> None:
    source = MemorySource({"PORT": "8080"})

    env = Env({"PORT": int}, sources=[source])

    assert env.PORT == 8080
    assert env.sources == (source,)


def test_sources_property_exposes_the_source_objects(tmp_path: Path) -> None:
    path = write_file(tmp_path, ".env", "PORT=8080\n")

    env = Env({"PORT": int}, sources=[str(path)])
    source = env.sources[0]

    assert isinstance(source, FileSource)
    assert source.path == path


def test_invalid_source_specification_raises_type_error() -> None:
    invalid: Any = object()

    with pytest.raises(TypeError) as exc_info:
        Env({"PORT": int}, sources=[invalid])

    assert "load()" in str(exc_info.value)


def test_unknown_source_string_raises_value_error() -> None:
    with pytest.raises(ValueError):
        Env({"PORT": int}, sources=["nowhere.ini"])


def test_missing_source_file_is_skipped_with_a_warning(tmp_path: Path) -> None:
    env = Env({"PORT": int}, sources=[str(tmp_path / "missing.env")])

    assert len(env) == 0
    assert any("missing.env" in warning and "skipped" in warning for warning in env.warnings)
    assert env.valid is True


def test_missing_source_file_raises_in_strict_mode(tmp_path: Path) -> None:
    with pytest.raises(MissingSourceError) as exc_info:
        Env({"PORT": int}, sources=[str(tmp_path / "missing.env")], strict=True)

    assert "missing.env" in str(exc_info.value)


def test_corrupt_source_always_raises(tmp_path: Path) -> None:
    path = write_file(tmp_path, "broken.json", '{"a": ')

    with pytest.raises(SourceLoadError):
        Env({"A": str}, sources=[str(path)])


def test_empty_source_list_resolves_nothing() -> None:
    env = Env({"PORT": int}, sources=[])

    assert len(env) == 0
    assert env.dict() == {}


# --- access patterns ---------------------------------------------------------


def test_attribute_and_item_access_return_the_same_value() -> None:
    env = Env({"PORT": int}, sources=[MemorySource({"PORT": "8080"})])

    assert env.PORT == 8080
    assert env["PORT"] == 8080


def test_get_returns_the_value_or_the_default() -> None:
    env = Env({"PORT": int}, sources=[MemorySource({"PORT": "8080"})])

    assert env.get("PORT") == 8080
    assert env.get("MISSING") is None
    assert env.get("MISSING", "fallback") == "fallback"


def test_dict_returns_every_cast_value() -> None:
    env = Env(
        {"PORT": int, "DEBUG": bool},
        sources=[MemorySource({"PORT": "8080", "DEBUG": "yes"})],
    )

    assert env.dict() == {"PORT": 8080, "DEBUG": True}


def test_dict_returns_a_copy() -> None:
    env = Env({"PORT": int}, sources=[MemorySource({"PORT": "8080"})])

    snapshot = env.dict()
    snapshot["PORT"] = 1
    snapshot["NEW"] = 2

    assert env.PORT == 8080
    assert "NEW" not in env


def test_json_returns_a_valid_json_document() -> None:
    env = Env(
        {"PORT": int, "HOSTS": List[str]},
        sources=[MemorySource({"PORT": "8080", "HOSTS": "a,b"})],
    )

    assert json.loads(env.json()) == {"PORT": 8080, "HOSTS": ["a", "b"]}


def test_json_forwards_dump_options() -> None:
    env = Env({"PORT": int}, sources=[MemorySource({"PORT": "8080"})])

    assert env.json(indent=2) == '{\n  "PORT": 8080\n}'


def test_contains_reports_resolved_keys_only() -> None:
    env = Env(
        {"PORT": int, "DEBUG": Optional[bool]},
        sources=[MemorySource({"PORT": "8080"})],
    )

    assert "PORT" in env
    assert "DEBUG" not in env
    assert "MISSING" not in env


def test_len_and_iter_cover_the_resolved_keys() -> None:
    env = Env(
        {"PORT": int, "DEBUG": bool},
        sources=[MemorySource({"PORT": "8080", "DEBUG": "yes"})],
    )

    assert len(env) == 2
    assert list(env) == ["PORT", "DEBUG"]
    assert sorted(env) == ["DEBUG", "PORT"]


def test_repr_masks_sensitive_values() -> None:
    env = Env(
        {"PORT": int, "SECRET_KEY": str, "API_TOKEN": str},
        sources=[MemorySource({"PORT": "8080", "SECRET_KEY": "hunter2", "API_TOKEN": "abc123"})],
    )

    rendered = repr(env)

    assert rendered.startswith("Env(")
    assert "PORT=8080" in rendered
    assert "hunter2" not in rendered
    assert "abc123" not in rendered
    assert "'***'" in rendered


def test_repr_of_an_empty_env() -> None:
    assert repr(Env({"PORT": int}, sources=[])) == "Env()"


def test_missing_key_error_on_attribute_access() -> None:
    env = Env({"PORT": int}, sources=[])

    with pytest.raises(MissingKeyError) as exc_info:
        _ = env.PORT

    assert exc_info.value.key == "PORT"
    assert "declared in the schema" in str(exc_info.value)


def test_missing_key_error_on_item_access() -> None:
    env = Env({"PORT": int}, sources=[])

    with pytest.raises(MissingKeyError) as exc_info:
        env["PORT"]

    assert exc_info.value.key == "PORT"


def test_missing_required_key_message_mentions_required() -> None:
    env = Env({"PORT": int}, sources=[], required=["PORT"])

    with pytest.raises(MissingKeyError) as exc_info:
        env["PORT"]

    assert "required key" in str(exc_info.value)


def test_undeclared_key_lookup_explains_that_it_is_not_declared() -> None:
    env = Env({"PORT": int}, sources=[])

    with pytest.raises(MissingKeyError) as exc_info:
        env["NOPE"]

    assert "not declared in the schema" in str(exc_info.value)


def test_private_attributes_raise_attribute_error() -> None:
    env = Env({"PORT": int}, sources=[])
    attribute = "_definitely_not_a_key"

    with pytest.raises(AttributeError):
        getattr(env, attribute)

    assert hasattr(env, attribute) is False


def test_missing_attributes_follow_standard_python_lookup_behavior() -> None:
    env = Env({"PORT": int}, sources=[])

    assert hasattr(env, "PORT") is False
    assert getattr(env, "PORT", 8080) == 8080
    with pytest.raises(KeyError):
        env["PORT"]


# --- strictness, validators and warnings -------------------------------------


def test_strict_mode_raises_for_a_missing_required_key() -> None:
    with pytest.raises(ValidationError) as exc_info:
        Env({"PORT": int}, sources=[MemorySource({})], required=["PORT"], strict=True)

    error = exc_info.value
    assert any("PORT" in message for message in error.errors)
    assert "missing required key 'PORT'" in str(error)


def test_strict_mode_raises_for_a_value_that_cannot_be_cast() -> None:
    with pytest.raises(ValidationError) as exc_info:
        Env({"PORT": int}, sources=[MemorySource({"PORT": "abc"})], strict=True)

    assert any("cannot cast" in message for message in exc_info.value.errors)


def test_strict_mode_accepts_valid_values() -> None:
    env = Env(
        {"PORT": int},
        sources=[MemorySource({"PORT": "8080"})],
        required=["PORT"],
        strict=True,
    )

    assert env.PORT == 8080
    assert env.valid is True
    assert env.errors == []
    assert env.strict is True


def test_non_strict_mode_collects_every_problem_without_raising() -> None:
    env = Env(
        {"PORT": int, "HOST": str},
        sources=[MemorySource({"HOST": "localhost", "PORT": "abc"})],
        required=["PORT", "MISSING"],
    )

    assert env.valid is False
    assert any("cannot cast" in message for message in env.errors)
    assert any("MISSING" in message for message in env.errors)
    assert env.HOST == "localhost"
    assert "PORT" not in env


def test_custom_validators_receive_cast_values() -> None:
    seen: List[Any] = []

    def record(value: Any) -> bool:
        seen.append(value)
        return True

    env = Env(
        {"PORT": int},
        sources=[MemorySource({"PORT": "8080"})],
        validators={"PORT": record},
    )

    assert seen == [8080]
    assert env.valid is True


def test_custom_validator_failure_is_recorded_in_non_strict_mode() -> None:
    env = Env(
        {"PORT": int},
        sources=[MemorySource({"PORT": "10"})],
        validators={"PORT": lambda value: "PORT must be at least 1024"},
    )

    assert env.valid is False
    assert "PORT must be at least 1024" in env.errors
    assert env.PORT == 10


def test_custom_validator_failure_raises_in_strict_mode() -> None:
    with pytest.raises(ValidationError):
        Env(
            {"PORT": int},
            sources=[MemorySource({"PORT": "10"})],
            validators={"PORT": lambda value: "PORT must be at least 1024"},
            strict=True,
        )


def test_required_key_without_a_schema_entry_warns() -> None:
    env = Env(
        {"PORT": int},
        sources=[MemorySource({"PORT": "8080", "API_KEY": "x"})],
        required=["API_KEY"],
    )

    assert env.valid is True
    assert any("API_KEY" in warning for warning in env.warnings)


def test_hot_reload_starts_a_watcher_or_warns() -> None:
    env = Env({"PORT": int}, sources=[MemorySource({"PORT": "8080"})], hot_reload=True)

    if env.watcher is None:
        assert any("hot_reload" in warning for warning in env.warnings)

    assert env.hot_reload is True
    env.close()


def test_hot_reload_disabled_produces_no_watcher_or_warning() -> None:
    env = Env({"PORT": int}, sources=[MemorySource({"PORT": "8080"})])

    assert env.hot_reload is False
    assert env.watcher is None
    assert env.warnings == []


# --- lifecycle ---------------------------------------------------------------


def test_reload_picks_up_file_changes(tmp_path: Path) -> None:
    path = write_file(tmp_path, ".env", "PORT=8080\n")
    env = Env({"PORT": int}, sources=[str(path)])

    write_file(tmp_path, ".env", "PORT=9090\n")
    env.reload()

    assert env.PORT == 9090


def test_reload_calls_the_on_reload_callback(tmp_path: Path) -> None:
    path = write_file(tmp_path, ".env", "PORT=8080\n")
    seen: List[Env] = []

    env = Env({"PORT": int}, sources=[str(path)], on_reload=seen.append)
    write_file(tmp_path, ".env", "PORT=9090\n")
    env.reload()

    assert seen == [env]


def test_reload_raises_in_strict_mode_when_the_new_values_are_invalid(tmp_path: Path) -> None:
    path = write_file(tmp_path, ".env", "PORT=8080\n")
    env = Env({"PORT": int}, sources=[str(path)], required=["PORT"], strict=True)

    write_file(tmp_path, ".env", "PORT=abc\n")

    with pytest.raises(ValidationError):
        env.reload()


def test_reload_refreshes_errors(tmp_path: Path) -> None:
    path = write_file(tmp_path, ".env", "PORT=8080\n")
    env = Env({"PORT": int}, sources=[str(path)], required=["PORT"])
    assert env.valid is True

    write_file(tmp_path, ".env", "PORT=nope\n")
    env.reload()

    assert env.valid is False
    assert env.errors


def test_close_is_idempotent_and_keeps_values_readable() -> None:
    env = Env({"PORT": int}, sources=[MemorySource({"PORT": "8080"})])

    env.close()
    env.close()

    assert env.closed is True
    assert env.PORT == 8080


def test_context_manager_closes_the_env() -> None:
    with Env({"PORT": int}, sources=[MemorySource({"PORT": "8080"})]) as env:
        assert env.PORT == 8080

    assert env.closed is True


def test_schema_and_required_properties() -> None:
    schema = {"PORT": int, "HOST": str}
    env = Env(schema, sources=[], required=["PORT", "PORT"])

    assert env.schema == schema
    assert env.required == ("PORT",)

    schema_copy = env.schema
    schema_copy["NEW"] = str
    assert env.schema == schema


# --- thread safety and integration -------------------------------------------


def test_concurrent_reads_and_reloads_are_safe(tmp_path: Path) -> None:
    path = write_file(tmp_path, ".env", "PORT=8080\nHOST=localhost\n")
    env = Env({"PORT": int, "HOST": str}, sources=[str(path)])
    barrier = threading.Barrier(5)
    failures: List[BaseException] = []

    def reader() -> None:
        try:
            barrier.wait(timeout=10)
            for _ in range(200):
                assert env.PORT == 8080
                assert env.get("PORT") == 8080
                assert env.dict() == {"PORT": 8080, "HOST": "localhost"}
                assert len(env) == 2
                assert "PORT" in env
                assert sorted(env) == ["HOST", "PORT"]
        except BaseException as exc:  # pragma: no cover - only on a race
            failures.append(exc)

    def writer() -> None:
        try:
            barrier.wait(timeout=10)
            for _ in range(50):
                env.reload()
        except BaseException as exc:  # pragma: no cover - only on a race
            failures.append(exc)

    threads = [threading.Thread(target=reader) for _ in range(4)]
    threads.append(threading.Thread(target=writer))
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert failures == []
    assert env.PORT == 8080


def test_end_to_end_with_environment_dotenv_and_json_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PORT", "1")
    dotenv_path = write_file(tmp_path, ".env", "PORT=8080\nHOST=from-dotenv\n")
    json_path = write_file(tmp_path, "config.json", '{"host": "from-json", "debug": true}')

    env = Env(
        {"PORT": int, "HOST": str, "DEBUG": bool},
        sources=["os", str(dotenv_path), str(json_path)],
        required=["PORT"],
    )

    assert env.PORT == 1
    assert env.HOST == "from-dotenv"
    assert env.DEBUG is True
    assert env.dict() == {"PORT": 1, "HOST": "from-dotenv", "DEBUG": True}
    assert json.loads(env.json())["PORT"] == 1
    assert repr(env) == "Env(DEBUG=True, HOST='from-dotenv', PORT=1)"
    assert env.valid is True


def test_pydantic_model_can_be_used_as_a_schema() -> None:
    pydantic = pytest.importorskip("pydantic")

    model = pydantic.create_model("Settings", port=(int, ...), host=(str, "localhost"))

    env = Env(model, sources=[MemorySource({"port": "8080", "host": "db"})])

    assert env.dict() == {"port": 8080, "host": "db"}
    assert env.schema == {"port": int, "host": str}


def test_strict_failed_reload_keeps_last_good_snapshot_and_report(tmp_path: Path) -> None:
    path = write_file(tmp_path, ".env", "PORT=8080\n")
    seen: List[Env] = []
    env = Env({"PORT": int}, sources=[str(path)], strict=True, on_reload=seen.append)
    original_source = env.get_source("PORT")

    path.write_text("PORT=invalid\n", encoding="utf-8")
    with pytest.raises(ValidationError, match="cannot cast"):
        env.reload()

    assert env.PORT == 8080
    assert env.valid is True
    assert env.errors == []
    assert env.warnings == []
    assert env.get_source("PORT") == original_source
    assert seen == []

    path.write_text("PORT=9090\n", encoding="utf-8")
    env.reload()
    assert env.PORT == 9090
    assert seen == [env]


@pytest.mark.parametrize("strict", [True, False])
def test_source_failure_keeps_previous_snapshot(tmp_path: Path, strict: bool) -> None:
    path = write_file(tmp_path, "config.json", '{"port": 8080}')
    env = Env({"PORT": int}, sources=[str(path)], strict=strict)
    path.write_text("{", encoding="utf-8")

    with pytest.raises(SourceLoadError):
        env.reload()

    assert env.dict() == {"PORT": 8080}
    assert env.valid is True


def test_custom_caster_runs_once_and_validator_sees_retained_object() -> None:
    class Value:
        def __init__(self, value: str) -> None:
            self.value = value

    cast_values: List[Value] = []
    validated_values: List[Value] = []

    def convert(value: str) -> Value:
        converted = Value(value)
        cast_values.append(converted)
        return converted

    def check(value: Value) -> bool:
        validated_values.append(value)
        return True

    env = Env(
        {"ITEM": convert}, sources=[MemorySource({"ITEM": "data"})], validators={"ITEM": check}
    )

    assert len(cast_values) == 1
    assert env.ITEM is cast_values[0]
    assert env.ITEM is validated_values[0]
    env.reload()
    assert len(cast_values) == 2
    assert env.ITEM is cast_values[1]
    assert env.ITEM is validated_values[1]


def test_nested_mutable_values_cannot_be_changed_through_accessors() -> None:
    env = Env({"ITEMS": list}, sources=[MemorySource({"ITEMS": '[{"names": ["original"]}]'})])
    env.ITEMS[0]["names"].append("attribute")
    env["ITEMS"][0]["names"].append("item")
    env.get("ITEMS")[0]["names"].append("get")
    env.dict()["ITEMS"][0]["names"].append("snapshot")

    assert env.ITEMS == [{"names": ["original"]}]


def test_validator_cannot_mutate_committed_builtin_values_later() -> None:
    validated: List[Any] = []

    def record(value: Any) -> bool:
        validated.append(value)
        return True

    env = Env(
        {"ITEMS": list},
        sources=[MemorySource({"ITEMS": "one,two"})],
        validators={"ITEMS": record},
    )
    validated[0].append("later")

    assert env.ITEMS == ["one", "two"]


def test_env_accepts_path_objects(tmp_path: Path) -> None:
    path = write_file(tmp_path, ".env.production", "PORT=8080\n")

    env = Env({"PORT": int}, sources=[path])

    assert env.PORT == 8080
    assert env.get_source("PORT") == ".env.production"


def test_defaults_are_cast_validated_and_lower_priority_than_all_sources() -> None:
    env = Env(
        {"PORT": int, "HOST": str, "DEBUG": bool},
        sources=[MemorySource({"PORT": "8080"}, "first"), MemorySource({"HOST": "db"}, "last")],
        defaults={"PORT": 80, "HOST": "local", "DEBUG": "false", "UNKNOWN": "ignored"},
        required=["DEBUG"],
        strict=True,
    )

    assert env.dict() == {"PORT": 8080, "HOST": "db", "DEBUG": False}
    assert env.get_source("PORT") == "first"
    assert env.get_source("HOST") == "last"
    assert env.get_source("DEBUG") == "defaults"
    with pytest.raises(MissingKeyError):
        env.get_source("UNKNOWN")


def test_defaults_use_the_same_validation_rules_as_sources() -> None:
    with pytest.raises(ValidationError, match="cannot cast"):
        Env({"PORT": int}, sources=[], defaults={"PORT": "bad"}, strict=True)
    with pytest.raises(ValidationError, match="too low"):
        Env(
            {"PORT": int},
            sources=[],
            defaults={"PORT": 1},
            validators={"PORT": lambda value: "too low"},
            strict=True,
        )


def test_mutable_defaults_are_isolated_from_input_and_future_reloads() -> None:
    defaults = {"ITEMS": [{"nested": [1]}]}
    env = Env({"ITEMS": list}, sources=[], defaults=defaults)
    defaults["ITEMS"][0]["nested"].append(2)
    env.ITEMS[0]["nested"].append(3)
    env.reload()

    assert env.ITEMS == [{"nested": [1]}]


def test_empty_source_value_does_not_fall_through_to_default() -> None:
    env = Env({"PORT": int}, sources=[MemorySource({"PORT": ""})], defaults={"PORT": 8080})
    assert "PORT" not in env
    with pytest.raises(MissingKeyError):
        env.get_source("PORT")


def test_provenance_updates_after_reload() -> None:
    first = MemorySource({"PORT": "8080"}, "first")
    env = Env({"PORT": int}, sources=[first], defaults={"PORT": 80})
    first._data.clear()
    env.reload()

    assert env.PORT == 80
    assert env.get_source("PORT") == "defaults"


def test_redacted_exports_are_opt_in_and_do_not_mutate_values() -> None:
    env = Env(
        {"PORT": int, "DB_PASS": str}, sources=[MemorySource({"PORT": "8080", "DB_PASS": "secret"})]
    )

    assert env.dict(redact=True) == {"PORT": 8080, "DB_PASS": "***"}
    assert json.loads(env.json(redact=True)) == env.dict(redact=True)
    assert env.dict()["DB_PASS"] == "secret"
    assert "secret" not in repr(env)


def test_concurrent_refreshes_are_serialized_without_blocking_readers() -> None:
    entered = threading.Event()
    second_started = threading.Event()
    second_entered = threading.Event()
    release = threading.Event()
    failures: List[BaseException] = []

    class SlowSource(BaseSource):
        name = "slow"

        def __init__(self) -> None:
            self.calls = 0

        def load(self) -> Dict[str, str]:
            self.calls += 1
            number = self.calls
            if number == 2:
                entered.set()
                assert release.wait(10)
            if number == 3:
                second_entered.set()
            return {"NUMBER": str(number), "MATCH": str(number)}

    source = SlowSource()
    env = Env({"NUMBER": int, "MATCH": int}, sources=[source])

    def reload_env(signal: Optional[threading.Event] = None) -> None:
        try:
            if signal is not None:
                signal.set()
            env.reload()
        except BaseException as exc:
            failures.append(exc)

    first = threading.Thread(target=reload_env)
    second = threading.Thread(target=reload_env, args=(second_started,))
    first.start()
    try:
        assert entered.wait(5)
        second.start()
        assert second_started.wait(5)
        assert not second_entered.wait(0.1)
        assert env.dict() == {"NUMBER": 1, "MATCH": 1}
    finally:
        release.set()
        first.join(timeout=5)
        if second.ident is not None:
            second.join(timeout=5)

    assert failures == []
    assert not first.is_alive()
    assert not second.is_alive()
    assert env.dict() == {"NUMBER": 3, "MATCH": 3}
