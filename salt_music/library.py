"""Local music library: artists -> albums -> tracks, read from tags."""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from pathlib import Path

import mutagen

from . import naming

AUDIO_EXT = {".opus", ".m4a", ".mp3", ".flac", ".ogg"}


@dataclass
class LibTrack:
    path: Path
    title: str
    artist: str
    album: str
    number: int


@dataclass
class LibAlbum:
    title: str
    folder: Path
    tracks: list[LibTrack] = field(default_factory=list)


@dataclass
class LibArtist:
    name: str
    albums: dict[str, LibAlbum] = field(default_factory=dict)
    image: Path | None = None

    @property
    def tracks(self) -> list[LibTrack]:
        return [t for a in self.albums.values() for t in a.tracks]


def _first(tags, *names) -> str:
    for n in names:
        v = tags.get(n) if tags else None
        if v:
            return str(v[0]).strip()
    return ""


def _number(raw: str) -> int:
    try:
        return int(raw.split("/")[0])
    except ValueError:
        return 0


@dataclass(frozen=True)
class _Info:
    title: str
    album_artist: str
    album: str
    number: int
    artists: tuple[str, ...]  # every name from albumartist / artist, split on commas


# Reading tags is the slow part of a scan; files that did not change are not reread.
_cache: dict[Path, tuple[int, int, _Info]] = {}
_cache_lock = threading.Lock()
CACHE_MAX = 50_000


def _info(path: Path) -> _Info:
    try:
        st = path.stat()
        stamp = (st.st_mtime_ns, st.st_size)
    except OSError:
        stamp = (0, 0)
    with _cache_lock:
        hit = _cache.get(path)
    if hit and hit[:2] == stamp:
        return hit[2]
    try:
        f = mutagen.File(path, easy=True)
        tags = f.tags if f else None
    except Exception:
        tags = None
    names: list[str] = []
    for n in ("albumartist", "artist"):
        for v in (tags.get(n) or []) if tags else []:
            names.extend(x.strip() for x in str(v).split(","))
    info = _Info(_first(tags, "title"), _first(tags, "albumartist", "artist"), _first(tags, "album"),
                 _number(_first(tags, "tracknumber")), tuple(n for n in names if n))
    with _cache_lock:
        if len(_cache) >= CACHE_MAX:
            _cache.clear()
        _cache[path] = (*stamp, info)
    return info


def read(path: Path) -> LibTrack:
    i = _info(path)
    return LibTrack(path, i.title or path.stem, i.album_artist or path.parent.parent.name,
                    i.album or path.parent.name, i.number)


def scan(base: Path) -> list[LibArtist]:
    artists: dict[str, LibArtist] = {}
    if not base.is_dir():
        return []
    for p in sorted(base.rglob("*")):
        if p.suffix.lower() not in AUDIO_EXT or not p.is_file():
            continue
        t = read(p)
        a = artists.setdefault(naming.key(t.artist), LibArtist(t.artist))
        album = a.albums.setdefault(naming.key(t.album), LibAlbum(t.album, p.parent))
        album.tracks.append(t)
        if a.image is None:
            for cand in (p.parent / "artist.jpg", p.parent.parent / "artist.jpg"):
                if cand.exists():
                    a.image = cand
                    break
    for a in artists.values():
        for al in a.albums.values():
            al.tracks.sort(key=lambda t: (t.number or 999, naming.key(t.title)))
    return sorted(artists.values(), key=lambda a: naming.key(a.name))


def index(base: Path) -> set[tuple[str, str]]:
    """(artist key, title key) of every audio file under base, for "already have it" checks."""
    out: set[tuple[str, str]] = set()
    if not base.is_dir():
        return out
    for p in base.rglob("*"):
        if p.suffix.lower() not in AUDIO_EXT or not p.is_file():
            continue
        i = _info(p)
        title = naming.key(i.title or re.sub(r"^\d+\.\s*", "", p.stem))
        names = {p.parent.parent.name, *i.artists}
        out.update((naming.key(n), title) for n in names if n)
    return out


def files_for_push(tracks: list[LibTrack], base: Path, covers: bool = True) -> list[Path]:
    """Audio files plus cover.jpg / artist.jpg found next to them (inside base)."""
    out: list[Path] = []
    seen: set[Path] = set()

    def add(p: Path):
        if p not in seen and p.is_file() and base in p.parents:
            seen.add(p)
            out.append(p)

    for t in tracks:
        add(t.path)
        if not covers:
            continue
        add(t.path.parent / "cover.jpg")
        add(t.path.parent / "artist.jpg")
        add(t.path.parent.parent / "artist.jpg")
    return out


def remove_moved(files: list[Path], base: Path) -> None:
    """After "move to phone": delete the audio files, then folders left without music."""
    dirs: set[Path] = set()
    for f in files:
        if f.suffix.lower() in AUDIO_EXT and base in f.parents:
            try:
                f.unlink()
            except OSError:
                continue
            dirs.update(d for d in f.parents if base in d.parents)
    for d in sorted(dirs, key=lambda d: len(d.parts), reverse=True):
        try:
            if any(p.suffix.lower() in AUDIO_EXT for p in d.rglob("*")):
                continue
            for extra in ("cover.jpg", "artist.jpg"):
                (d / extra).unlink(missing_ok=True)
            d.rmdir()  # only if nothing else is left there
        except OSError:
            pass
