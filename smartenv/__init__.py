"""smartenv — unified, type-safe, multi-source environment and config management.

Load configuration from the process environment, ``.env`` files, JSON, TOML, YAML
or cloud secret managers, cast every value to the type declared in a schema and
validate it before it reaches your code::

    from smartenv import Env

    env = Env({"PORT": int, "DEBUG": bool}, sources=["os", ".env"], required=["PORT"])

    env.PORT                  # 8080, an int
    env.get("MISSING", "x")   # "x"
    env.dict()                # {"PORT": 8080, "DEBUG": True}

There are no mandatory dependencies: PyYAML, watchdog, tomli, pydantic and the
cloud SDKs are optional extras (``pip install smartenv-config[yaml]``, ...). The
``TomlSource`` and ``YamlSource`` classes are available from
:mod:`smartenv.sources` and are imported on first use.

Example:
    >>> from smartenv import Env
    >>> class MemorySource:
    ...     name = "memory"
    ...     def load(self):
    ...         return {"PORT": "8080"}
    >>> Env({"PORT": int}, sources=[MemorySource()]).PORT
    8080
"""

from __future__ import annotations

from smartenv._version import __version__
from smartenv.casters import FALSE_VALUES, TRUE_VALUES, can_cast, cast
from smartenv.core import Env
from smartenv.exceptions import (
    CastError,
    CloudAuthError,
    MissingKeyError,
    MissingSourceError,
    SmartEnvError,
    SourceLoadError,
    ValidationError,
)
from smartenv.schema import get_default_value, normalize_schema
from smartenv.sources import (
    BaseSource,
    DotenvSource,
    FileSource,
    JsonSource,
    OsSource,
    flatten_mapping,
    resolve_source,
)
from smartenv.validators import ValidationResult, validate, validate_or_raise

__all__ = [
    "FALSE_VALUES",
    "TRUE_VALUES",
    "BaseSource",
    "CastError",
    "CloudAuthError",
    "DotenvSource",
    "Env",
    "FileSource",
    "JsonSource",
    "MissingKeyError",
    "MissingSourceError",
    "OsSource",
    "SmartEnvError",
    "SourceLoadError",
    "ValidationError",
    "ValidationResult",
    "can_cast",
    "cast",
    "flatten_mapping",
    "get_default_value",
    "normalize_schema",
    "resolve_source",
    "validate",
    "validate_or_raise",
    "__version__",
]
