"""Safe file names and path templates.

Names are always cleaned by the strictest rules (Windows / FAT / Android),
because files end up on the phone too.
"""

from __future__ import annotations

import re
import sys
import unicodedata
from pathlib import Path

FORBIDDEN = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]')
RESERVED = {
    "CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$",
    *(f"{dev}{n}" for dev in ("COM", "LPT") for n in (*"123456789", "\u00b9", "\u00b2", "\u00b3")),
}
MAX_BYTES = 255
# Leave room for extensions and yt-dlp temp suffixes (".part", ".temp.opus").
STEM_BYTES = 200

# Whole-path limit in UTF-16 units. Windows still refuses longer paths in many
# places (Explorer, older players) even with long paths enabled in the registry.
PATH_LIMIT = 240 if sys.platform == "win32" else 4000
STEM_MIN = 40  # a file name is never cut shorter than this to save room
PART_MIN = 24

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
    if name.split(".")[0].rstrip(" ").upper() in RESERVED:
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
    # On Windows `folder / name` exists whatever its case, so the listing is what
    # tells the real spelling: paths shown and saved match the disk.
    wanted = key(name)
    similar = None
    try:
        for child in folder.iterdir():
            if child.name == name:
                return child
            if similar is None and key(child.name) == wanted and child.is_dir():
                similar = child
    except OSError:
        pass
    if similar is None and (folder / name).exists():
        return folder / name
    return similar


def track_number(n: int | None, total: int | None = None) -> str:
    if not n:
        return ""
    width = max(2, len(str(total or 0)))
    return str(n).zfill(width)


def _u16(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def _cut_u16(text: str, limit: int) -> str:
    raw = text.encode("utf-16-le")[: max(limit, 1) * 2]
    out = raw.decode("utf-16-le", "ignore").rstrip(" .")
    return out or text[:1]


def fit(base: Path, parts: list[str], stem: str, room: int = 20,
        limit: int | None = None) -> tuple[list[str], str]:
    """Shorten folder names and the file stem so base/parts/stem+suffix stays under the limit.

    `room` is kept for the extension and yt-dlp temp suffixes. Folders are cut the
    same way for every track of a release (they never depend on the stem), so an
    album never splits into two folders.
    """
    limit = PATH_LIMIT if limit is None else limit
    parts = list(parts)
    folder_budget = limit - room - 1 - STEM_MIN

    def folder_len() -> int:
        return _u16(str(base)) + sum(_u16(p) + 1 for p in parts)

    while folder_len() > folder_budget:
        longest = max(range(len(parts)), key=lambda i: _u16(parts[i]), default=None)
        if longest is None or _u16(parts[longest]) <= PART_MIN:
            break  # the base folder itself is too deep: nothing sensible left to cut
        over = folder_len() - folder_budget
        parts[longest] = _cut_u16(parts[longest], max(_u16(parts[longest]) - over, PART_MIN))
    left = limit - room - 1 - folder_len()
    if _u16(stem) > left:
        stem = _cut_u16(stem, max(left, STEM_MIN))
    return parts, stem
