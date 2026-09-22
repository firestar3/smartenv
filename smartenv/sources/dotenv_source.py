"""``.env`` file source with a dependency free parser."""

from __future__ import annotations

import re
from typing import Dict, List, Tuple

from smartenv.sources.base import FileSource

__all__ = ["DotenvSource", "parse_dotenv"]

_KEY_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")
"""Keys must start with a letter or underscore and may contain letters, digits,
``_``, ``.`` or ``-``."""

_ESCAPES: Dict[str, str] = {
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "\\": "\\",
    '"': '"',
    "'": "'",
}
"""Backslash escapes understood inside double quoted values."""


class DotenvSource(FileSource):
    """Source backed by a ``.env`` file.

    The parser is intentionally dependency free (no ``python-dotenv``) and
    understands the syntax that shows up in real ``.env`` files:

    * ``KEY=VALUE``, whitespace around the separator is ignored;
    * ``KEY="VALUE"`` — double quoted, may span several lines, resolves the
      escapes ``\\n``, ``\\r``, ``\\t``, ``\\\\``, ``\\"`` and ``\\'``;
    * ``KEY='VALUE'`` — single quoted, literal content on one line;
    * ``export KEY=VALUE``, the ``export`` prefix is dropped;
    * blank lines and lines whose first non blank character is ``#``;
    * trailing comments after unquoted values (``KEY=value # comment``), where a
      ``#`` only starts a comment at the start of the value or after whitespace,
      so values such as ``http://host/#frag`` are kept intact.

    Malformed lines are skipped silently and, when a key is defined several
    times, the last definition wins. Files are decoded as UTF-8.

    Example:
        >>> from smartenv.sources.dotenv_source import parse_dotenv
        >>> parse_dotenv("PLAIN=value")
        {'PLAIN': 'value'}
        >>> parse_dotenv('DATABASE_URL="postgres://localhost" # local')
        {'DATABASE_URL': 'postgres://localhost'}
    """

    def load(self) -> Dict[str, str]:
        """Parse the backing file.

        Returns:
            The key/value pairs defined in the file.

        Raises:
            MissingSourceError: If the file does not exist.
            SourceLoadError: If the file cannot be read.
        """
        return parse_dotenv(self.read_text())


def parse_dotenv(text: str) -> Dict[str, str]:
    """Parse ``.env`` text into a mapping of key to value.

    Args:
        text: Decoded content of a ``.env`` file.

    Returns:
        The parsed key/value pairs. Malformed lines are skipped silently and the
        last definition of a repeated key wins.

    Example:
        >>> parse_dotenv("A=1\\nB='two'\\n# comment\\nC=three # trailing\\n")
        {'A': '1', 'B': 'two', 'C': 'three'}
    """
    result: Dict[str, str] = {}
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index].lstrip()
        index += 1
        if not line or line.startswith("#"):
            continue
        if line.startswith("export") and (len(line) == 6 or line[6].isspace()):
            line = line[6:].lstrip()
        key, separator, raw_value = line.partition("=")
        if not separator:
            continue
        key = key.strip()
        if not _KEY_PATTERN.match(key):
            continue
        value_text = raw_value.lstrip()
        if value_text.startswith('"'):
            value, closed, index = _read_double_quoted(value_text[1:], lines, index)
            if closed:
                result[key] = value
            continue
        if value_text.startswith("'"):
            end = value_text.find("'", 1)
            if end != -1:
                result[key] = value_text[1:end]
            continue
        result[key] = _strip_comment(value_text)
    return result


def _read_double_quoted(first: str, lines: List[str], index: int) -> Tuple[str, bool, int]:
    """Read a double quoted value, following it across line breaks.

    Args:
        first: Text that followed the opening quote on the first line.
        lines: All lines of the file, without terminators.
        index: Position of the next unread line.

    Returns:
        ``(value, closed, next_index)``. ``closed`` is ``False`` for an
        unterminated value, in which case ``next_index`` points at the line after
        the opening one so the caller can resume parsing there instead of
        swallowing the rest of the file.
    """
    start_index = index
    parts: List[str] = []
    current = first
    while True:
        closing = _find_closing_quote(current)
        if closing != -1:
            parts.append(current[:closing])
            return _unescape("\n".join(parts)), True, index
        parts.append(current)
        if index >= len(lines):
            return "", False, start_index
        current = lines[index]
        index += 1


def _find_closing_quote(text: str) -> int:
    """Return the index of the first unescaped double quote in ``text``.

    Args:
        text: Text to scan.

    Returns:
        The index of the closing quote, or ``-1`` when ``text`` contains none.
    """
    escaped = False
    for position, character in enumerate(text):
        if escaped:
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == '"':
            return position
    return -1


def _strip_comment(value: str) -> str:
    """Remove a trailing comment from an unquoted value.

    A ``#`` starts a comment at the beginning of the value or when it is preceded
    by whitespace, so ``KEY=value # note`` yields ``"value"`` while
    ``KEY=http://host/#frag`` keeps its fragment.

    Args:
        value: Unquoted value text.

    Returns:
        The value without its trailing comment, with surrounding whitespace stripped.
    """
    for position, character in enumerate(value):
        if character == "#" and (position == 0 or value[position - 1].isspace()):
            return value[:position].rstrip()
    return value.rstrip()


def _unescape(value: str) -> str:
    """Resolve backslash escapes inside a double quoted value.

    Recognised escapes are ``\\n``, ``\\r``, ``\\t``, ``\\\\``, ``\\"`` and
    ``\\'``. Unknown escapes keep their backslash (``\\d`` stays ``\\d``), which
    matches shell behaviour and avoids corrupting Windows paths.

    Args:
        value: Raw text found between the double quotes.

    Returns:
        The unescaped value.
    """
    if "\\" not in value:
        return value
    result: List[str] = []
    escaped = False
    for character in value:
        if escaped:
            result.append(_ESCAPES.get(character, "\\" + character))
            escaped = False
        elif character == "\\":
            escaped = True
        else:
            result.append(character)
    if escaped:
        result.append("\\")
    return "".join(result)
