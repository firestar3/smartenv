"""TOML file source."""

from __future__ import annotations

import importlib
from types import ModuleType
from typing import Any, Dict, Mapping, Optional

from smartenv.exceptions import SourceLoadError
from smartenv.sources.base import FileSource, flatten_mapping

__all__ = ["TomlSource"]

_MISSING_PARSER_MESSAGE = (
    "TOML support requires the standard library 'tomllib' module (Python 3.11+) or "
    "the 'tomli' package on older interpreters; install it with: pip install smartenv[toml]"
)


def _import_parser() -> ModuleType:
    """Import the best available TOML parser.

    ``tomllib`` is used on Python 3.11 and newer, ``tomli`` everywhere else.

    Returns:
        The imported parser module.

    Raises:
        ImportError: If neither module is installed.
    """
    for module_name in ("tomllib", "tomli"):
        try:
            return importlib.import_module(module_name)
        except ModuleNotFoundError:
            continue
    raise ImportError(_MISSING_PARSER_MESSAGE)


_PARSER: Optional[ModuleType] = _import_parser()
"""The TOML parser resolved when this module is imported."""


class TomlSource(FileSource):
    """Source backed by a TOML document.

    Nested tables are flattened with the double underscore separator and every
    value is converted to a string, exactly like
    :class:`~smartenv.sources.json_source.JsonSource` and
    :class:`~smartenv.sources.yaml_source.YamlSource`.

    Importing this module raises :class:`ImportError` when no TOML parser is
    available, so :func:`smartenv.sources.resolve_source` imports it lazily.
    """

    def load(self) -> Dict[str, str]:
        """Load and flatten the TOML document.

        Returns:
            Flat ``KEY``/``SECTION__KEY`` string pairs.

        Raises:
            MissingSourceError: If the file does not exist.
            SourceLoadError: If the file cannot be read or contains invalid TOML.
        """
        if _PARSER is None:  # pragma: no cover - guarded by the import above
            raise ImportError(_MISSING_PARSER_MESSAGE)
        text = self.read_text()
        try:
            data: Any = _PARSER.loads(text)
        except ValueError as exc:
            raise SourceLoadError(str(self.path), reason=f"invalid TOML: {exc}") from exc
        if not isinstance(data, Mapping):
            raise SourceLoadError(str(self.path), reason="expected a TOML table at the top level")
        return flatten_mapping(data)
