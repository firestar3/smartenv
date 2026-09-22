"""Shared, conservative masking rules for configuration diagnostics.

Masking is based on key names. It is a logging aid, not a secret store: explicit
configuration access and structured exception attributes still contain values.
"""

from __future__ import annotations

from typing import Any, Tuple

__all__ = ["is_sensitive_key", "mask_value"]

_SENSITIVE_MARKERS: Tuple[str, ...] = (
    "AUTH",
    "CERT",
    "CREDENTIAL",
    "KEY",
    "PASS",
    "PRIVATE",
    "SECRET",
    "TOKEN",
)


def is_sensitive_key(key: str) -> bool:
    """Report whether a key name suggests credentials or other secret data.

    Args:
        key: Configuration key, matched case insensitively.

    Returns:
        ``True`` when the key contains a sensitive marker.
    """
    upper = key.upper()
    return any(marker in upper for marker in _SENSITIVE_MARKERS)


def mask_value(key: str, value: Any, mask: str = "***") -> Any:
    """Replace a sensitive value with a fixed display mask.

    Args:
        key: Configuration key used to decide whether to mask.
        value: Value to display.
        mask: Replacement string for a sensitive value.

    Returns:
        The mask for a sensitive key, otherwise the original value.
    """
    return mask if is_sensitive_key(key) else value
