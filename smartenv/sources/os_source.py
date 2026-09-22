"""Source backed by the process environment."""

from __future__ import annotations

import os
from typing import Dict

from smartenv.sources.base import BaseSource

__all__ = ["OsSource"]


class OsSource(BaseSource):
    """Source backed by ``os.environ``.

    Example:
        >>> from smartenv.sources import OsSource
        >>> OsSource().name
        'os'
    """

    @property
    def name(self) -> str:
        """Return the identifier of the source.

        Returns:
            Always ``"os"``.
        """
        return "os"

    def load(self) -> Dict[str, str]:
        """Return a snapshot of the process environment.

        Returns:
            ``dict(os.environ)``. The copy is independent, so mutating it does
            not change the process environment and vice versa.
        """
        return dict(os.environ)
