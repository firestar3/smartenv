"""Configuration sources and the :func:`resolve_source` factory.

Only the sources that live on the standard library are imported eagerly, so
``import smartenv.sources`` always succeeds. The TOML, YAML and cloud sources
(:class:`AwsSource`, :class:`GcpSource` and :class:`AzureSource`) are imported
the first time they are requested, which keeps their optional dependencies
optional.

Example:
    >>> from smartenv.sources import resolve_source
    >>> resolve_source("os").name
    'os'
    >>> resolve_source("config/.env").name
    '.env'
"""

from __future__ import annotations

import importlib
from typing import Any, Dict, Tuple, Type

from smartenv.sources.base import BaseSource, FileSource, flatten_mapping
from smartenv.sources.dotenv_source import DotenvSource
from smartenv.sources.json_source import JsonSource
from smartenv.sources.os_source import OsSource

__all__ = [
    "BaseSource",
    "AwsSource",
    "AzureSource",
    "CloudSource",
    "DotenvSource",
    "FileSource",
    "GcpSource",
    "JsonSource",
    "OsSource",
    "TomlSource",
    "YamlSource",
    "flatten_mapping",
    "parse_secret_payload",
    "resolve_source",
]

_CLOUD_SOURCES: Dict[str, Tuple[str, str, str]] = {
    "aws_secrets": ("smartenv.sources.aws_source", "AwsSource", "smartenv[aws]"),
    "gcp_secrets": ("smartenv.sources.gcp_source", "GcpSource", "smartenv[gcp]"),
    "azure_secrets": ("smartenv.sources.azure_source", "AzureSource", "smartenv[azure]"),
}
"""Cloud provider names mapped to ``(module, class, extra)`` tuples."""

_FILE_SOURCES: Tuple[Tuple[Tuple[str, ...], str, str], ...] = (
    ((".env",), "smartenv.sources.dotenv_source", "DotenvSource"),
    ((".json",), "smartenv.sources.json_source", "JsonSource"),
    ((".toml",), "smartenv.sources.toml_source", "TomlSource"),
    ((".yaml", ".yml"), "smartenv.sources.yaml_source", "YamlSource"),
)
"""File extensions mapped to ``(suffixes, module, class)`` tuples, checked in order."""

_LAZY_ATTRIBUTES: Dict[str, str] = {
    "TomlSource": "smartenv.sources.toml_source",
    "YamlSource": "smartenv.sources.yaml_source",
    "AwsSource": "smartenv.sources.aws_source",
    "GcpSource": "smartenv.sources.gcp_source",
    "AzureSource": "smartenv.sources.azure_source",
    "CloudSource": "smartenv.sources.base",
    "parse_secret_payload": "smartenv.sources.base",
}
"""Sources that are imported on first attribute access (PEP 562)."""


def resolve_source(source_string: str) -> BaseSource:
    """Build the source described by ``source_string``.

    The argument is matched case insensitively and may be:

    * ``"os"`` — the process environment;
    * ``"aws_secrets"``, ``"gcp_secrets"`` or ``"azure_secrets"`` — a cloud
      secret manager, imported lazily;
    * a path ending in ``.env``, ``.json``, ``.toml``, ``.yaml`` or ``.yml``.

    Args:
        source_string: Description of the source to build.

    Returns:
        A ready to use :class:`BaseSource`.

    Raises:
        ValueError: If the string is empty or describes an unsupported source.
        ImportError: If an optional dependency of the requested source is missing.

    Example:
        >>> resolve_source("settings.json")
        <JsonSource name='settings.json'>
    """
    candidate = source_string.strip()
    lowered = candidate.lower()

    if lowered == "os":
        return OsSource()

    cloud = _CLOUD_SOURCES.get(lowered)
    if cloud is not None:
        return _load_cloud_source(lowered, cloud)

    for suffixes, module_name, class_name in _FILE_SOURCES:
        if lowered.endswith(suffixes):
            return _import_file_source(module_name, class_name)(candidate)

    raise ValueError(
        f"unknown source {source_string!r}; expected 'os', a cloud provider name "
        "('aws_secrets', 'gcp_secrets', 'azure_secrets') or a path ending in "
        ".env, .json, .toml, .yaml or .yml"
    )


def _import_file_source(module_name: str, class_name: str) -> Type[FileSource]:
    """Import a file backed source class by name.

    Args:
        module_name: Dotted module path, e.g. ``"smartenv.sources.toml_source"``.
        class_name: Name of the class inside that module.

    Returns:
        The imported class, ready to be instantiated with a path.

    Raises:
        ImportError: If the module cannot be imported, typically because an
            optional dependency such as ``tomli`` or ``PyYAML`` is missing.
    """
    module = importlib.import_module(module_name)
    source_class: Type[FileSource] = getattr(module, class_name)
    return source_class


def _load_cloud_source(key: str, spec: Tuple[str, str, str]) -> BaseSource:
    """Import and instantiate a cloud source on first use.

    Args:
        key: Provider name, e.g. ``"aws_secrets"``.
        spec: ``(module, class, extra)`` tuple from :data:`_CLOUD_SOURCES`.

    Returns:
        The instantiated cloud source.

    Raises:
        ImportError: If the module or one of its optional dependencies is missing.
    """
    module_name, class_name, extra = spec
    try:
        module = importlib.import_module(module_name)
        source_class: Type[BaseSource] = getattr(module, class_name)
    except ImportError as exc:
        raise ImportError(
            f"the {key!r} source is unavailable ({exc}); install it with: pip install {extra}"
        ) from exc
    return source_class()


def __getattr__(name: str) -> Any:
    """Import optional sources on first attribute access.

    Args:
        name: Attribute requested on the package.

    Returns:
        The imported optional source class, cached in the module namespace.

    Raises:
        AttributeError: If the attribute is unknown.
    """
    module_name = _LAZY_ATTRIBUTES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(module_name), name)
    globals()[name] = value
    return value
