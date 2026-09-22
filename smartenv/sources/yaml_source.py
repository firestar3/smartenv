"""YAML file source."""

from __future__ import annotations

from typing import Any, Dict, Mapping

from smartenv.exceptions import SourceLoadError
from smartenv.sources.base import FileSource, flatten_mapping

__all__ = ["YamlSource"]

_MISSING_PARSER_MESSAGE = (
    "YAML support requires the 'PyYAML' package; install it with: pip install smartenv-config[yaml]"
)

try:
    import yaml as _yaml
except ImportError as exc:  # pragma: no cover - depends on the environment
    raise ImportError(_MISSING_PARSER_MESSAGE) from exc


class YamlSource(FileSource):
    """Source backed by a YAML document.

    The document is read with ``yaml.safe_load``, so no arbitrary Python objects
    can be constructed from untrusted files. Nested mappings are flattened with
    the double underscore separator and every value is converted to a string,
    exactly like :class:`~smartenv.sources.json_source.JsonSource` and
    :class:`~smartenv.sources.toml_source.TomlSource`.

    Importing this module raises :class:`ImportError` when PyYAML is not
    installed, so :func:`smartenv.sources.resolve_source` imports it lazily.
    """

    def load(self) -> Dict[str, str]:
        """Load and flatten the YAML document.

        Returns:
            Flat ``KEY``/``SECTION__KEY`` string pairs; an empty document yields
            an empty mapping.

        Raises:
            MissingSourceError: If the file does not exist.
            SourceLoadError: If the file cannot be read, is not valid YAML or does
                not contain a mapping at the top level.
        """
        text = self.read_text()
        try:
            data: Any = _yaml.safe_load(text)
        except Exception as exc:  # PyYAML raises several YAMLError subclasses.
            raise SourceLoadError(str(self.path), reason=f"invalid YAML: {exc}") from exc
        if data is None:
            return {}
        if not isinstance(data, Mapping):
            raise SourceLoadError(str(self.path), reason="expected a YAML mapping at the top level")
        return flatten_mapping(data)
