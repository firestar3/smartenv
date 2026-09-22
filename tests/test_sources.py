"""Tests for :mod:`smartenv.sources`."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

from smartenv.casters import cast
from smartenv.exceptions import MissingSourceError, SourceLoadError
from smartenv.sources import BaseSource, resolve_source
from smartenv.sources.base import flatten_mapping
from smartenv.sources.dotenv_source import DotenvSource, parse_dotenv
from smartenv.sources.json_source import JsonSource
from smartenv.sources.os_source import OsSource


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


def require_toml() -> None:
    """Skip the calling test when no TOML parser is installed."""
    if importlib.util.find_spec("tomllib") is None and importlib.util.find_spec("tomli") is None:
        pytest.skip("no TOML parser available")


def require_yaml() -> None:
    """Skip the calling test when PyYAML is not installed."""
    if importlib.util.find_spec("yaml") is None:
        pytest.skip("PyYAML is not installed")


# --- OsSource ----------------------------------------------------------------


def test_os_source_name() -> None:
    assert OsSource().name == "os"


def test_os_source_returns_the_process_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SMARTENV_OS_SOURCE_TEST", "hello")

    loaded = OsSource().load()

    assert loaded["SMARTENV_OS_SOURCE_TEST"] == "hello"
    assert loaded == dict(os.environ)


def test_os_source_returns_an_isolated_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SMARTENV_OS_SOURCE_TEST", "hello")

    loaded = OsSource().load()
    loaded["SMARTENV_OS_SOURCE_TEST"] = "changed"
    loaded["SMARTENV_BRAND_NEW_KEY"] = "value"

    assert os.environ["SMARTENV_OS_SOURCE_TEST"] == "hello"
    assert "SMARTENV_BRAND_NEW_KEY" not in os.environ


def test_os_source_is_a_base_source() -> None:
    assert isinstance(OsSource(), BaseSource)


# --- DotenvSource ------------------------------------------------------------


def test_dotenv_source_parses_plain_quoted_and_exported_values(tmp_path: Path) -> None:
    path = write_file(
        tmp_path,
        ".env",
        "\n".join(
            [
                "# a comment",
                "",
                "   ",
                "PLAIN=value",
                'DOUBLE="double value"',
                "SINGLE='single value'",
                "export EXPORTED=exported-value",
                "SPACED = spaced ",
                "EMPTY=",
            ]
        )
        + "\n",
    )

    assert DotenvSource(path).load() == {
        "PLAIN": "value",
        "DOUBLE": "double value",
        "SINGLE": "single value",
        "EXPORTED": "exported-value",
        "SPACED": "spaced",
        "EMPTY": "",
    }


def test_dotenv_source_handles_inline_comments(tmp_path: Path) -> None:
    path = write_file(
        tmp_path,
        ".env",
        "\n".join(
            [
                "PLAIN=value # trailing comment",
                "NO_SPACE=value#kept",
                "URL=http://example.com/#frag",
                'QUOTED="value # not a comment"',
                "SINGLE='another # literal'",
            ]
        )
        + "\n",
    )

    loaded = DotenvSource(path).load()

    assert loaded["PLAIN"] == "value"
    assert loaded["NO_SPACE"] == "value#kept"
    assert loaded["URL"] == "http://example.com/#frag"
    assert loaded["QUOTED"] == "value # not a comment"
    assert loaded["SINGLE"] == "another # literal"


def test_dotenv_source_reads_multi_line_double_quoted_values(tmp_path: Path) -> None:
    path = write_file(
        tmp_path,
        ".env",
        "\n".join(
            [
                'QUERY="SELECT *',
                'FROM users"',
                "AFTER=still-parsed",
            ]
        )
        + "\n",
    )

    loaded = DotenvSource(path).load()

    assert loaded["QUERY"] == "SELECT *\nFROM users"
    assert loaded["AFTER"] == "still-parsed"


def test_dotenv_source_resolves_escapes_and_keeps_unknown_ones(tmp_path: Path) -> None:
    path = write_file(
        tmp_path,
        ".env",
        "\n".join(
            [
                'ESCAPES="line1\\nline2\\tend"',
                'QUOTED_QUOTE="say \\"hi\\""',
                'WINDOWS="C:\\Users\\me\\file.txt"',
                'UNKNOWN="\\d+\\s*"',
            ]
        )
        + "\n",
    )

    loaded = DotenvSource(path).load()

    assert loaded["ESCAPES"] == "line1\nline2\tend"
    assert loaded["QUOTED_QUOTE"] == 'say "hi"'
    assert loaded["WINDOWS"] == "C:\\Users\\me\\file.txt"
    assert loaded["UNKNOWN"] == "\\d+\\s*"


def test_dotenv_source_skips_malformed_lines(tmp_path: Path) -> None:
    path = write_file(
        tmp_path,
        ".env",
        "\n".join(
            [
                "this is not a key value pair",
                "=missing-key",
                "1NUMBER=leading-digit",
                'UNTERMINATED="no closing quote',
                "GOOD=value",
            ]
        )
        + "\n",
    )

    assert DotenvSource(path).load() == {"GOOD": "value"}


def test_dotenv_source_keeps_unicode_values(tmp_path: Path) -> None:
    path = write_file(tmp_path, ".env", 'GREETING=héllo ✓\nQUOTED="naïve — ✓"\n')

    assert DotenvSource(path).load() == {"GREETING": "héllo ✓", "QUOTED": "naïve — ✓"}


def test_dotenv_source_ignores_a_utf8_bom(tmp_path: Path) -> None:
    path = write_file(tmp_path, ".env", "\ufeffFIRST=1\n")

    assert DotenvSource(path).load() == {"FIRST": "1"}


def test_dotenv_source_last_definition_wins(tmp_path: Path) -> None:
    path = write_file(tmp_path, ".env", "KEY=first\nKEY=second\n")

    assert parse_dotenv(path.read_text(encoding="utf-8")) == {"KEY": "second"}


def test_dotenv_source_name_and_path(tmp_path: Path) -> None:
    path = write_file(tmp_path, ".env", "A=1\n")
    source = DotenvSource(path)

    assert source.name == ".env"
    assert source.path == path
    assert source.exists() is True


def test_dotenv_source_missing_file_raises(tmp_path: Path) -> None:
    missing = tmp_path / "missing.env"

    with pytest.raises(MissingSourceError) as exc_info:
        DotenvSource(missing).load()

    assert exc_info.value.source == str(missing)
    assert "missing.env" in str(exc_info.value)


def test_dotenv_source_unterminated_single_quote_is_skipped(tmp_path: Path) -> None:
    path = write_file(tmp_path, ".env", "BROKEN='no closing quote\nAFTER=1\n")

    assert DotenvSource(path).load() == {"AFTER": "1"}


def test_dotenv_source_directory_path_raises_missing_source(tmp_path: Path) -> None:
    with pytest.raises(MissingSourceError):
        DotenvSource(tmp_path).load()


# --- JsonSource --------------------------------------------------------------


def test_json_source_flattens_flat_documents(tmp_path: Path) -> None:
    path = write_file(tmp_path, "flat.json", '{"HOST": "localhost", "PORT": 8080}')

    assert JsonSource(path).load() == {"HOST": "localhost", "PORT": "8080"}


def test_json_source_flattens_nested_documents(tmp_path: Path) -> None:
    path = write_file(tmp_path, "nested.json", '{"database": {"host": "localhost", "port": 5432}}')

    assert JsonSource(path).load() == {
        "DATABASE__HOST": "localhost",
        "DATABASE__PORT": "5432",
    }


def test_json_source_flattens_any_depth_and_converts_values(tmp_path: Path) -> None:
    path = write_file(
        tmp_path,
        "deep.json",
        '{"a": {"b": {"c": {"d": "value"}}}, "list": [1, 2], "flag": true, '
        '"nothing": null, "ratio": 0.5}',
    )

    assert JsonSource(path).load() == {
        "A__B__C__D": "value",
        "LIST": "[1,2]",
        "FLAG": "true",
        "NOTHING": "",
        "RATIO": "0.5",
    }


def test_json_source_uppercases_keys(tmp_path: Path) -> None:
    path = write_file(tmp_path, "mixed.json", '{"mixedCase": {"inner_key": "v"}}')

    assert JsonSource(path).load() == {"MIXEDCASE__INNER_KEY": "v"}


def test_json_source_values_are_all_strings(tmp_path: Path) -> None:
    path = write_file(tmp_path, "types.json", '{"int": 1, "float": 1.5, "text": "x", "yes": true}')

    loaded = JsonSource(path).load()

    assert all(isinstance(value, str) for value in loaded.values())
    assert loaded == {"INT": "1", "FLOAT": "1.5", "TEXT": "x", "YES": "true"}


def test_json_source_flattened_lists_round_trip_through_cast(tmp_path: Path) -> None:
    path = write_file(tmp_path, "list.json", '{"tags": ["a", "b"]}')

    assert cast(JsonSource(path).load()["TAGS"], List[str]) == ["a", "b"]


def test_json_source_invalid_json_raises(tmp_path: Path) -> None:
    path = write_file(tmp_path, "broken.json", '{"a": ')

    with pytest.raises(SourceLoadError) as exc_info:
        JsonSource(path).load()

    assert "invalid JSON" in exc_info.value.reason
    assert exc_info.value.source == str(path)


def test_json_source_top_level_array_raises(tmp_path: Path) -> None:
    path = write_file(tmp_path, "array.json", "[1, 2, 3]")

    with pytest.raises(SourceLoadError) as exc_info:
        JsonSource(path).load()

    assert "JSON object" in exc_info.value.reason


def test_json_source_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(MissingSourceError):
        JsonSource(tmp_path / "missing.json").load()


def test_json_source_name_exists_and_repr(tmp_path: Path) -> None:
    path = write_file(tmp_path, "app.json", "{}")
    source = JsonSource(path)

    assert source.name == "app.json"
    assert source.exists() is True
    assert JsonSource(tmp_path / "missing.json").exists() is False
    assert repr(source) == "<JsonSource name='app.json'>"


# --- TomlSource --------------------------------------------------------------


def test_toml_source_flattens_tables(tmp_path: Path) -> None:
    require_toml()
    from smartenv.sources.toml_source import TomlSource

    path = write_file(
        tmp_path,
        "settings.toml",
        "\n".join(
            [
                'title = "smartenv"',
                "debug = true",
                "",
                "[database]",
                'host = "localhost"',
                "port = 5432",
                'tags = ["a", "b"]',
                "",
                "[database.pool]",
                "size = 5",
            ]
        )
        + "\n",
    )

    assert TomlSource(path).load() == {
        "TITLE": "smartenv",
        "DEBUG": "true",
        "DATABASE__HOST": "localhost",
        "DATABASE__PORT": "5432",
        "DATABASE__TAGS": '["a","b"]',
        "DATABASE__POOL__SIZE": "5",
    }


def test_toml_source_invalid_document_raises(tmp_path: Path) -> None:
    require_toml()
    from smartenv.sources.toml_source import TomlSource

    path = write_file(tmp_path, "broken.toml", "key = \n")

    with pytest.raises(SourceLoadError) as exc_info:
        TomlSource(path).load()

    assert "invalid TOML" in exc_info.value.reason
    assert exc_info.value.source == str(path)


def test_toml_source_name_and_missing_file(tmp_path: Path) -> None:
    require_toml()
    from smartenv.sources.toml_source import TomlSource

    assert TomlSource(write_file(tmp_path, "app.toml", "a = 1\n")).name == "app.toml"
    with pytest.raises(MissingSourceError):
        TomlSource(tmp_path / "missing.toml").load()


# --- YamlSource --------------------------------------------------------------


def test_yaml_source_flattens_flat_documents(tmp_path: Path) -> None:
    require_yaml()
    from smartenv.sources.yaml_source import YamlSource

    path = write_file(tmp_path, "flat.yaml", "host: localhost\nport: 8080\n")

    assert YamlSource(path).load() == {"HOST": "localhost", "PORT": "8080"}


def test_yaml_source_flattens_nested_documents(tmp_path: Path) -> None:
    require_yaml()
    from smartenv.sources.yaml_source import YamlSource

    path = write_file(
        tmp_path,
        "nested.yaml",
        "\n".join(
            [
                "database:",
                "  host: localhost",
                "  port: 5432",
                "  pool:",
                "    size: 5",
                "  options:",
                "    - one",
                "    - two",
                "features:",
                "  cache: yes",
            ]
        )
        + "\n",
    )

    assert YamlSource(path).load() == {
        "DATABASE__HOST": "localhost",
        "DATABASE__PORT": "5432",
        "DATABASE__POOL__SIZE": "5",
        "DATABASE__OPTIONS": '["one","two"]',
        "FEATURES__CACHE": "true",
    }


def test_yaml_source_empty_document_is_an_empty_mapping(tmp_path: Path) -> None:
    require_yaml()
    from smartenv.sources.yaml_source import YamlSource

    assert YamlSource(write_file(tmp_path, "empty.yaml", "")).load() == {}


def test_yaml_source_invalid_document_raises(tmp_path: Path) -> None:
    require_yaml()
    from smartenv.sources.yaml_source import YamlSource

    path = write_file(tmp_path, "broken.yaml", "key: [unclosed\n")

    with pytest.raises(SourceLoadError) as exc_info:
        YamlSource(path).load()

    assert "invalid YAML" in exc_info.value.reason


def test_yaml_source_top_level_sequence_raises(tmp_path: Path) -> None:
    require_yaml()
    from smartenv.sources.yaml_source import YamlSource

    path = write_file(tmp_path, "list.yaml", "- one\n- two\n")

    with pytest.raises(SourceLoadError) as exc_info:
        YamlSource(path).load()

    assert "mapping" in exc_info.value.reason


def test_yaml_source_name_and_missing_file(tmp_path: Path) -> None:
    require_yaml()
    from smartenv.sources.yaml_source import YamlSource

    assert YamlSource(write_file(tmp_path, "settings.yml", "a: 1\n")).name == "settings.yml"
    with pytest.raises(MissingSourceError):
        YamlSource(tmp_path / "missing.yaml").load()


# --- flatten_mapping ---------------------------------------------------------


def test_flatten_mapping_uppercases_and_joins_nested_keys() -> None:
    assert flatten_mapping({"database": {"host": "localhost", "port": 5432}}) == {
        "DATABASE__HOST": "localhost",
        "DATABASE__PORT": "5432",
    }


def test_flatten_mapping_uses_a_custom_separator() -> None:
    assert flatten_mapping({"db": {"host": "x"}}, separator=".") == {"DB.HOST": "x"}


def test_flatten_mapping_json_encodes_sequences() -> None:
    assert flatten_mapping({"tags": ["a", "b"], "pair": (1, 2)}) == {
        "TAGS": '["a","b"]',
        "PAIR": "[1,2]",
    }


def test_flatten_mapping_converts_scalars() -> None:
    assert flatten_mapping({"yes": True, "no": False, "none": None, "num": 5, "ratio": 0.5}) == {
        "YES": "true",
        "NO": "false",
        "NONE": "",
        "NUM": "5",
        "RATIO": "0.5",
    }


def test_flatten_mapping_does_not_mutate_its_input() -> None:
    data: Dict[str, Any] = {"a": {"b": 1}}

    assert flatten_mapping(data) == {"A__B": "1"}
    assert data == {"a": {"b": 1}}


def test_flatten_mapping_skips_empty_nested_mappings() -> None:
    assert flatten_mapping({"empty": {}, "kept": {"value": 1}}) == {"KEPT__VALUE": "1"}


def test_flatten_mapping_preserves_document_order() -> None:
    flattened = flatten_mapping({"b": 1, "a": {"c": 2}})

    assert flattened == {"B": "1", "A__C": "2"}
    assert list(flattened) == ["B", "A__C"]


# --- resolve_source ----------------------------------------------------------


def test_resolve_source_returns_an_os_source() -> None:
    source = resolve_source("os")

    assert isinstance(source, OsSource)
    assert source.name == "os"


def test_resolve_source_is_case_insensitive_and_tolerates_whitespace() -> None:
    assert isinstance(resolve_source("  OS  "), OsSource)


def test_resolve_source_returns_a_dotenv_source(tmp_path: Path) -> None:
    source = resolve_source(str(tmp_path / ".env"))

    assert isinstance(source, DotenvSource)
    assert source.name == ".env"
    assert source.path == tmp_path / ".env"


def test_resolve_source_returns_a_json_source(tmp_path: Path) -> None:
    assert isinstance(resolve_source(str(tmp_path / "app.json")), JsonSource)


def test_resolve_source_returns_a_toml_source(tmp_path: Path) -> None:
    require_toml()
    from smartenv.sources.toml_source import TomlSource

    assert isinstance(resolve_source(str(tmp_path / "app.toml")), TomlSource)


@pytest.mark.parametrize("file_name", ["app.yaml", "app.yml", "APP.YML"])
def test_resolve_source_returns_a_yaml_source(tmp_path: Path, file_name: str) -> None:
    require_yaml()
    from smartenv.sources.yaml_source import YamlSource

    assert isinstance(resolve_source(str(tmp_path / file_name)), YamlSource)


@pytest.mark.parametrize("source_string", ["not-a-source", "", "   ", "config.ini"])
def test_resolve_source_rejects_unknown_strings(source_string: str) -> None:
    with pytest.raises(ValueError) as exc_info:
        resolve_source(source_string)

    assert "unknown source" in str(exc_info.value)


@pytest.mark.parametrize("provider", ["aws_secrets", "gcp_secrets", "azure_secrets"])
def test_resolve_source_imports_cloud_sources_lazily(provider: str) -> None:
    try:
        source = resolve_source(provider)
    except ImportError as exc:
        assert provider in str(exc)
        assert "pip install smartenv[" in str(exc)
        return

    assert isinstance(source, BaseSource)


def test_sources_package_exposes_optional_classes_lazily() -> None:
    import smartenv.sources as sources

    require_toml()
    assert sources.TomlSource.__name__ == "TomlSource"

    require_yaml()
    assert sources.YamlSource.__name__ == "YamlSource"


def test_sources_package_raises_attribute_error_for_unknown_attributes() -> None:
    import smartenv.sources as sources

    attribute = "definitely_not_a_source"

    with pytest.raises(AttributeError):
        getattr(sources, attribute)


def test_importing_sources_does_not_import_optional_dependencies() -> None:
    code = "import sys, smartenv.sources; print('yaml' in sys.modules, 'tomllib' in sys.modules)"

    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )

    assert result.stdout.strip() == "False False"
