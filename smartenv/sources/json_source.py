"""JSON file source."""

from __future__ import annotations

import json
from typing import Any, Dict, Mapping

from smartenv.exceptions import SourceLoadError
from smartenv.sources.base import FileSource, flatten_mapping

__all__ = ["JsonSource"]


class JsonSource(FileSource):
    """Source backed by a JSON document.

    Nested objects are flattened with the double underscore separator and every
    value is converted to a string, exactly like
    :class:`~smartenv.sources.toml_source.TomlSource` and
    :class:`~smartenv.sources.yaml_source.YamlSource`::

        {"database": {"host": "localhost", "port": 5432}}
        -> {"DATABASE__HOST": "localhost", "DATABASE__PORT": "5432"}
    """

    def load(self) -> Dict[str, str]:
        """Load and flatten the JSON document.

        Returns:
            Flat ``KEY``/``SECTION__KEY`` string pairs.

        Raises:
            MissingSourceError: If the file does not exist.
            SourceLoadError: If the file cannot be read, is not valid JSON or
                does not contain a JSON object at the top level.
        """
        text = self.read_text()
        try:
            data: Any = json.loads(text)
        except ValueError as exc:
            raise SourceLoadError(str(self.path), reason=f"invalid JSON: {exc}") from exc
        if not isinstance(data, Mapping):
            raise SourceLoadError(str(self.path), reason="expected a JSON object at the top level")
        return flatten_mapping(data)
