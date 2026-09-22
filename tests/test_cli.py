"""CLI behavior, including exit statuses, schema metadata and secret masking."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from smartenv.cli import main


def write_file(directory: Path, name: str, contents: str) -> Path:
    """Write a UTF-8 test fixture and return its path."""
    path = directory / name
    path.write_text(contents, encoding="utf-8")
    return path


def test_validate_success(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    schema = write_file(
        tmp_path, "schema.py", "schema = {'PORT': int, 'DEBUG': bool}\nrequired = ['PORT']\n"
    )
    source = write_file(tmp_path, ".env", "PORT=8080\nDEBUG=true\n")

    assert main(["validate", "--schema", str(schema), "--sources", str(source)]) == 0
    assert capsys.readouterr().out == "\u2713 Validation passed\n"


def test_validate_reports_all_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    schema = write_file(
        tmp_path,
        "schema.py",
        "schema = {'DATABASE_URL': str, 'PORT': int}\nrequired = ['DATABASE_URL']\n",
    )
    source = write_file(tmp_path, ".env", "PORT=invalid\n")

    assert main(["validate", "--schema", str(schema), "--sources", str(source)]) == 1
    output = capsys.readouterr().out
    assert "\u2717 missing required key 'DATABASE_URL'" in output
    assert "\u2717" in output and "PORT" in output and "int" in output
    assert "Validation passed" not in output


def test_validate_optional_key_may_be_absent(tmp_path: Path) -> None:
    schema = write_file(tmp_path, "schema.py", "schema = {'PORT': int}\n")
    source = write_file(tmp_path, ".env", "")

    assert main(["validate", "--schema", str(schema), "--sources", str(source)]) == 0


def test_validate_custom_validator_receives_cast_value(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    schema = write_file(
        tmp_path,
        "schema.py",
        "schema = {'PORT': int}\nvalidators = {'PORT': lambda value: value > 0 or 'PORT must be positive'}\n",
    )
    source = write_file(tmp_path, ".env", "PORT=-1\n")

    assert main(["validate", "--schema", str(schema), "--sources", str(source)]) == 1
    assert "\u2717 PORT must be positive" in capsys.readouterr().out


def test_validate_emits_warnings(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    schema = write_file(
        tmp_path, "schema.py", "schema = {'PORT': int}\nvalidators = {'PORT': lambda value: True}\n"
    )
    source = write_file(tmp_path, ".env", "")

    assert main(["validate", "--schema", str(schema), "--sources", str(source)]) == 0
    assert "Warning: validator for 'PORT' was skipped" in capsys.readouterr().out


def test_validate_defaults_to_os(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    schema = write_file(
        tmp_path,
        "schema.py",
        "schema = {'SMARTENV_CLI_TEST_PORT': int}\nrequired = ['SMARTENV_CLI_TEST_PORT']\n",
    )
    monkeypatch.setenv("SMARTENV_CLI_TEST_PORT", "8080")

    assert main(["validate", "--schema", str(schema)]) == 0
    assert "Validation passed" in capsys.readouterr().out


def test_validate_keeps_first_source_priority(tmp_path: Path) -> None:
    schema = write_file(tmp_path, "schema.py", "schema = {'PORT': int, 'DEBUG': bool}\n")
    first = write_file(tmp_path, "first.env", "PORT=8080\n")
    fallback = write_file(tmp_path, "fallback.json", '{"PORT": "bad", "DEBUG": true}')

    assert main(["validate", "--schema", str(schema), "--sources", str(first), str(fallback)]) == 0


def test_generate_example_format(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    schema = write_file(
        tmp_path,
        "schema.py",
        "schema = {'DATABASE_URL': str, 'PORT': int}\nrequired = ['DATABASE_URL']\n",
    )
    output = tmp_path / ".env.example"

    assert main(["generate-example", "--schema", str(schema), "--output", str(output)]) == 0
    assert output.read_text(encoding="utf-8") == (
        "# DATABASE_URL (str) [REQUIRED]\nDATABASE_URL=\n# PORT (int) [optional]\nPORT=\n"
    )
    assert f"\u2713 Wrote {output}" in capsys.readouterr().out


def test_generate_example_typing_labels_and_utf8(tmp_path: Path) -> None:
    schema = write_file(
        tmp_path,
        "schema.py",
        "from typing import List, Optional\nschema = {'TAGS': List[str], 'CAF\u00c9': Optional[int]}\n",
    )
    output = tmp_path / ".env.example"

    assert main(["generate-example", "--schema", str(schema), "--output", str(output)]) == 0
    contents = output.read_text(encoding="utf-8")
    assert "# TAGS (List[str]) [optional]\nTAGS=" in contents
    assert "# CAF\u00c9 (Optional[int]) [optional]\nCAF\u00c9=" in contents


@pytest.mark.parametrize(
    "key", ["SECRET", "api_key", "Access_Token", "DATABASE_PASSWORD", "DB_PASS", "CREDENTIAL_FILE"]
)
def test_list_masks_sensitive_keys(
    key: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = write_file(tmp_path, ".env", f"{key}=do-not-expose-me\n")

    assert main(["list", "--sources", str(source)]) == 0
    assert capsys.readouterr().out == f"{key}=*****\n"


def test_list_shows_plaintext_and_first_source_priority(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    first = write_file(tmp_path, "first.env", "PORT=8080\nAPP_NAME=caf\u00e9\n")
    fallback = write_file(tmp_path, "fallback.json", '{"PORT": 9000, "DEBUG": true}')

    assert main(["list", "--sources", str(first), str(fallback)]) == 0
    assert capsys.readouterr().out == "APP_NAME=caf\u00e9\nDEBUG=true\nPORT=8080\n"


def test_check_source_success(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = write_file(tmp_path, ".env", "SECRET=not-printed\n")

    assert main(["check-source", "--source", str(source)]) == 0
    assert capsys.readouterr().out == f"\u2713 Connected to {source}\n"


def test_check_source_failure(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["check-source", "--source", "unknown-source"]) == 1
    assert "\u2717 Failed: unknown source 'unknown-source'" in capsys.readouterr().out


@pytest.mark.parametrize("command", ["validate", "list", "check-source"])
def test_missing_source_returns_failure(
    command: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "missing.env"
    arguments = [command]
    if command == "validate":
        schema = write_file(tmp_path, "schema.py", "schema = {}\n")
        arguments.extend(["--schema", str(schema)])
    arguments.extend(["--source" if command == "check-source" else "--sources", str(missing)])

    assert main(arguments) == 1
    assert "\u2717 Failed:" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("contents", "message"),
    [
        ("other = {}", "'schema' dictionary"),
        ("schema = []", "'schema' dictionary"),
        ("schema = {1: int}", "string keys"),
        ("schema = {}\nrequired = 'PORT'", "'required'"),
        ("schema = {}\nvalidators = {'PORT': 1}", "'validators'"),
        ("schema = {}\nraise RuntimeError('broken schema')", "broken schema"),
        ("schema = {", "Failed:"),
    ],
)
def test_invalid_schema_returns_failure(
    contents: str, message: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    schema = write_file(tmp_path, "schema.py", contents)

    assert main(["validate", "--schema", str(schema)]) == 1
    output = capsys.readouterr().out
    assert "\u2717 Failed:" in output and message in output


def test_generate_example_write_failure(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    schema = write_file(tmp_path, "schema.py", "schema = {'PORT': int}\n")

    assert main(["generate-example", "--schema", str(schema), "--output", str(tmp_path)]) == 1
    assert "\u2717 Failed:" in capsys.readouterr().out


@pytest.mark.parametrize(("contents", "status"), [("PORT=8080\n", 0), ("", 1)])
def test_module_entry_point_exit_status(tmp_path: Path, contents: str, status: int) -> None:
    schema = write_file(tmp_path, "schema.py", "schema = {'PORT': int}\nrequired = ['PORT']\n")
    source = write_file(tmp_path, ".env", contents)
    environment = dict(os.environ, PYTHONIOENCODING="ascii")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "smartenv.cli",
            "validate",
            "--schema",
            str(schema),
            "--sources",
            str(source),
        ],
        cwd=str(Path(__file__).resolve().parents[1]),
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert result.returncode == status, result.stderr
    assert ("\u2713" if status == 0 else "\u2717") in result.stdout
    assert result.stderr == ""


def test_invalid_command_uses_argparse_status() -> None:
    with pytest.raises(SystemExit) as error:
        main(["does-not-exist"])

    assert error.value.code == 2
