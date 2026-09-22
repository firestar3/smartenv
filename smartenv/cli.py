"""Command-line tools for validating, inspecting and documenting configuration.

Schema files are Python modules defining ``schema = {"PORT": int, ...}``.
They may also define ``required = ["PORT", ...]`` and a ``validators`` mapping,
with the same semantics as :class:`smartenv.Env`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from smartenv.sources import resolve_source
from smartenv.validators import Validator, validate

__all__ = ["main"]

_SENSITIVE_MARKERS: Tuple[str, ...] = (
    "SECRET",
    "KEY",
    "TOKEN",
    "PASSWORD",
    "PASS",
    "CREDENTIAL",
)


def _read_schema(path_string: str) -> Tuple[Dict[str, Any], List[str], Dict[str, Validator]]:
    """Execute a UTF-8 schema file and check its public configuration values."""
    path = Path(path_string).resolve()
    namespace: Dict[str, Any] = {"__file__": str(path), "__name__": "smartenv_schema"}
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace)
    schema = namespace.get("schema")
    if not isinstance(schema, dict) or any(not isinstance(key, str) for key in schema):
        raise ValueError("schema file must define a 'schema' dictionary with string keys")

    required = namespace.get("required", [])
    if (
        not isinstance(required, Sequence)
        or isinstance(required, (str, bytes))
        or any(not isinstance(key, str) for key in required)
    ):
        raise ValueError("schema file 'required' must be a sequence of key names")

    validators = namespace.get("validators", {})
    if not isinstance(validators, Mapping) or any(
        not isinstance(key, str) or not callable(value) for key, value in validators.items()
    ):
        raise ValueError("schema file 'validators' must map key names to callables")
    return dict(schema), list(required), dict(validators)


def _load_sources(sources: Sequence[str]) -> Dict[str, str]:
    """Merge explicitly requested sources, keeping the first value for each key."""
    values: Dict[str, str] = {}
    for description in sources:
        for key, value in resolve_source(description).load().items():
            values.setdefault(key, value)
    return values


def _type_label(type_hint: Any) -> str:
    """Format a schema type for an example-file comment."""
    if isinstance(type_hint, type):
        return type_hint.__name__
    return str(type_hint).replace("typing.", "")


def _validate_command(args: argparse.Namespace) -> int:
    """Report every validation error and return a shell-compatible status."""
    schema, required, validators = _read_schema(args.schema)
    values = _load_sources(args.sources)
    result = validate(values, schema, required, validators)
    for warning in result.warnings:
        print(f"Warning: {warning}")
    if result.is_valid:
        print("\u2713 Validation passed")
        return 0
    for error in result.errors:
        print(f"\u2717 {error}")
    return 1


def _generate_example_command(args: argparse.Namespace) -> int:
    """Write an empty, annotated entry for every schema key."""
    schema, required, _ = _read_schema(args.schema)
    lines: List[str] = []
    for key, type_hint in schema.items():
        status = "REQUIRED" if key in required else "optional"
        lines.extend((f"# {key} ({_type_label(type_hint)}) [{status}]", f"{key}="))
    Path(args.output).write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    print(f"\u2713 Wrote {args.output}")
    return 0


def _list_command(args: argparse.Namespace) -> int:
    """Print merged configuration, masking sensitive key names."""
    values = _load_sources(args.sources)
    for key in sorted(values):
        sensitive = any(marker in key.upper() for marker in _SENSITIVE_MARKERS)
        value = "*****" if sensitive else values[key]
        print(f"{key}={value}")
    return 0


def _check_source_command(args: argparse.Namespace) -> int:
    """Verify that a source can be instantiated and loaded."""
    resolve_source(args.source).load()
    print(f"\u2713 Connected to {args.source}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    """Build the standard-library-only command parser."""
    parser = argparse.ArgumentParser(
        prog="smartenv", description="Manage application configuration."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    validate_parser = commands.add_parser(
        "validate", help="Validate sources against a Python schema."
    )
    validate_parser.add_argument("--schema", required=True, help="Python file defining schema.")
    validate_parser.add_argument(
        "--sources", nargs="+", default=["os"], help="Sources in priority order."
    )
    validate_parser.set_defaults(handler=_validate_command)

    example_parser = commands.add_parser(
        "generate-example", help="Generate an annotated .env file."
    )
    example_parser.add_argument("--schema", required=True, help="Python file defining schema.")
    example_parser.add_argument("--output", default=".env.example", help="Output path.")
    example_parser.set_defaults(handler=_generate_example_command)

    list_parser = commands.add_parser("list", help="List values with sensitive keys masked.")
    list_parser.add_argument(
        "--sources", nargs="+", default=["os"], help="Sources in priority order."
    )
    list_parser.set_defaults(handler=_list_command)

    source_parser = commands.add_parser("check-source", help="Check source connectivity.")
    source_parser.add_argument("--source", required=True, help="Source name or file path.")
    source_parser.set_defaults(handler=_check_source_command)
    return parser


def _configure_output() -> None:
    """Use UTF-8 if a redirected terminal cannot encode the status symbols."""
    try:
        "\u2713\u2717".encode(sys.stdout.encoding or "utf-8")
    except UnicodeEncodeError:
        reconfigure = getattr(sys.stdout, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the smartenv CLI.

    Args:
        argv: Command arguments, or ``None`` to use the process arguments.

    Returns:
        Zero on success and one on a source, schema or validation failure.
        Invalid command syntax is handled by argparse with exit status two.
    """
    _configure_output()
    args = _build_parser().parse_args(argv)
    try:
        result: int = args.handler(args)
    except Exception as exc:
        print(f"\u2717 Failed: {exc}")
        return 1
    return result


if __name__ == "__main__":
    raise SystemExit(main())
