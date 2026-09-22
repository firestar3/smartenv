"""Exception hierarchy for :mod:`smartenv`.

Every exception raised by smartenv derives from :class:`SmartEnvError`, so a
single ``except SmartEnvError`` clause catches the whole family::

    from smartenv import SmartEnvError

    try:
        env.load()
    except SmartEnvError as exc:
        logger.error("configuration problem: %s", exc)

Besides a human readable ``str(exc)`` message, every exception carries
structured attributes (``key``, ``source``, ``target_type``, ``errors``, ...)
so callers can react programmatically instead of parsing strings.
"""

from __future__ import annotations

from typing import Any, Iterable, List, Optional

from smartenv.security import is_sensitive_key, mask_value

__all__ = [
    "SmartEnvError",
    "ValidationError",
    "CastError",
    "MissingKeyError",
    "MissingSourceError",
    "SourceLoadError",
    "CloudAuthError",
]


def _type_name(target: Any) -> str:
    """Return a readable name for a cast target.

    Args:
        target: A type, a ``typing`` construct or any callable used as a cast target.

    Returns:
        The bare class name for classes (``"int"``), otherwise ``str(target)``
        (``"typing.Optional[int]"``).
    """
    if isinstance(target, type):
        return target.__name__
    return str(target)


class SmartEnvError(Exception):
    """Base class for every smartenv error.

    Args:
        message: Human readable description of the failure.

    Attributes:
        message: Human readable description of the failure.
    """

    def __init__(self, message: str = "") -> None:
        self.message = message
        super().__init__(message)

    def __str__(self) -> str:
        """Return the human readable error message.

        Returns:
            The message, falling back to the class name when no message was given.
        """
        return self.message or type(self).__name__


class ValidationError(SmartEnvError):
    """Raised when a validation pass produced at least one error.

    Args:
        message: Optional summary message; a default summary is generated when omitted.
        errors: Errors collected by :func:`smartenv.validators.validate`.
        warnings: Non fatal problems collected during validation.

    Attributes:
        errors: Validation errors, in the order they were found.
        warnings: Non fatal problems found during validation.
    """

    def __init__(
        self,
        message: str = "",
        errors: Optional[Iterable[str]] = None,
        warnings: Optional[Iterable[str]] = None,
    ) -> None:
        self.errors: List[str] = list(errors or [])
        self.warnings: List[str] = list(warnings or [])
        if not message:
            plural = "" if len(self.errors) == 1 else "s"
            message = f"environment validation failed with {len(self.errors)} error{plural}"
        super().__init__(message)

    def __str__(self) -> str:
        """Return the summary followed by the individual errors and warnings.

        Returns:
            A multi line, bulleted report.
        """
        parts = [self.message]
        if self.errors:
            parts.append("errors:")
            for err in self.errors:
                parts.append(f"  - {err}")
        if self.warnings:
            parts.append("warnings:")
            for warning in self.warnings:
                parts.append(f"  - {warning}")
        return "\n".join(parts)


class CastError(SmartEnvError):
    """Raised when a raw value cannot be converted to the requested type.

    Args:
        value: The raw value that failed to cast.
        target_type: The type (or ``typing`` construct) the value was cast to.
        key: Optional environment/config key the value originated from.
        reason: Optional low level explanation, e.g. the underlying ``ValueError`` text.

    Attributes:
        key: Name of the offending key, or ``""`` when the caller did not supply one.
        value: String form of the offending value. This is unmasked; do not log it.
        target_type: The requested target type.
        reason: Unmasked low level explanation, or ``""``. Do not log it when
            handling sensitive configuration. Display messages redact sensitive
            values and reasons based on their key names.
    """

    def __init__(self, value: Any, target_type: Any, key: str = "", reason: str = "") -> None:
        self.key = key
        if value is None:
            self.value = "None"
        elif isinstance(value, str):
            self.value = value
        else:
            self.value = repr(value)
        self.target_type = target_type
        self.reason = reason
        super().__init__(self._build_message())

    def _build_message(self) -> str:
        """Compose the human readable message from the structured attributes.

        Returns:
            A message such as ``"key 'PORT': cannot cast 'abc' to int (invalid literal...)"``.
        """
        prefix = f"key {self.key!r}: " if self.key else ""
        display_value = mask_value(self.key, self.value)
        message = f"{prefix}cannot cast {display_value!r} to {_type_name(self.target_type)}"
        if self.reason and not is_sensitive_key(self.key):
            message = f"{message} ({self.reason})"
        return message


class MissingKeyError(SmartEnvError, AttributeError, KeyError):
    """Raised when a key is absent from the resolved configuration.

    Also an ``AttributeError`` and ``KeyError``, allowing normal ``hasattr``,
    ``getattr`` defaults, and dictionary-style exception handling.

    Args:
        key: Name of the missing key.
        message: Optional message overriding the generated one.

    Attributes:
        key: Name of the missing key.
    """

    def __init__(self, key: str, message: str = "") -> None:
        self.key = key
        super().__init__(message or f"missing required key {key!r}")


class MissingSourceError(SmartEnvError):
    """Raised when a source cannot be found or resolved.

    Args:
        source: Identifier of the source, typically a file path or a source name.
        message: Optional message overriding the generated one.

    Attributes:
        source: Identifier of the unavailable source.
    """

    def __init__(self, source: str, message: str = "") -> None:
        self.source = source
        super().__init__(message or f"source {source!r} is not registered or available")


class SourceLoadError(SmartEnvError):
    """Raised when an existing source cannot be read or parsed.

    Args:
        source: Identifier of the source, typically a file path or a source name.
        reason: Low level explanation, e.g. a parser or OS error message.
        message: Optional message overriding the generated one.

    Attributes:
        source: Identifier of the failing source.
        reason: Low level explanation, or ``""``.
    """

    def __init__(self, source: str, reason: str = "", message: str = "") -> None:
        self.source = source
        self.reason = reason
        super().__init__(
            message or "failed to load source {!r}: {}".format(source, reason or "unknown error")
        )


class CloudAuthError(SmartEnvError):
    """Raised when a cloud secret provider cannot authenticate.

    Args:
        provider: Cloud provider identifier, e.g. ``"aws"``, ``"gcp"`` or ``"azure"``.
        reason: Low level explanation, e.g. a missing credential chain message.
        message: Optional message overriding the generated one.

    Attributes:
        provider: Cloud provider identifier.
        reason: Low level explanation, or ``""``.
    """

    def __init__(self, provider: str, reason: str = "", message: str = "") -> None:
        self.provider = provider
        self.reason = reason
        super().__init__(
            message
            or "authentication with cloud provider {!r} failed: {}".format(
                provider, reason or "no credentials found"
            )
        )
