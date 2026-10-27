"""Safe file names and path templates.

Names are always cleaned by the strictest rules (Windows / FAT / Android),
because files end up on the phone too.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

FORBIDDEN = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]')
RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
MAX_BYTES = 255
# Leave room for extensions and yt-dlp temp suffixes (".part", ".temp.opus").
STEM_BYTES = 200

TOKENS = ("genre", "artist", "album", "year", "type", "track", "title")
TOKEN_RE = re.compile(r"\{(\w+)\}")


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def key(name: str) -> str:
    """Comparison key: same folder regardless of case / unicode form."""
    return nfc(name).casefold()


def _cut_bytes(text: str, limit: int) -> str:
    raw = text.encode("utf-8")
    if len(raw) <= limit:
        return text
    return raw[:limit].decode("utf-8", "ignore")


def clean(name: str, fallback: str = "Unknown", limit: int = STEM_BYTES) -> str:
    """Turn arbitrary text into one safe path component."""
    name = nfc(str(name or ""))
    name = FORBIDDEN.sub("_", name)
    name = re.sub(r"\s+", " ", name).strip()
    name = _cut_bytes(name, limit).rstrip(" .")
    name = name.lstrip(" ")
    if not name or set(name) <= {".", "_"}:
        name = fallback
    if name.split(".")[0].upper() in RESERVED:
        name = "_" + name
    return name


def render(template: str, values: dict[str, str]) -> list[str]:
    """Render a path template into a list of cleaned path components.

    Unknown tokens are kept literally. Empty components (e.g. no year) collapse.
    """
    parts = []
    for raw in re.split(r"[\\/]", template):
        text = TOKEN_RE.sub(lambda m: str(values.get(m.group(1), m.group(0))), raw)
        text = re.sub(r"^[\s\-–—.]+|[\s\-–—]+$", "", text)
        if text.strip():
            parts.append(clean(text))
    return parts


def resolve_dir(base: Path, parts: list[str]) -> Path:
    """Join parts onto base, reusing existing folders that differ only in case/form."""
    current = base
    for part in parts:
        current = _existing_child(current, part) or current / part
    return current


def _existing_child(folder: Path, name: str) -> Path | None:
    if not folder.is_dir():
        return None
    exact = folder / name
    if exact.exists():
        return exact
    wanted = key(name)
    try:
        for child in folder.iterdir():
            if child.is_dir() and key(child.name) == wanted:
                return child
    except OSError:
        pass
    return None


def track_number(n: int | None, total: int | None = None) -> str:
    if not n:
        return ""
    width = max(2, len(str(total or 0)))
    return str(n).zfill(width)
