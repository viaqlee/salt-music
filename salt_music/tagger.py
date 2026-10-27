"""Covers (square crop) and tags for opus / m4a / mp3 / flac via mutagen."""

from __future__ import annotations

import base64
import io
import logging
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, ID3, TALB, TCON, TDRC, TIT2, TPE1, TPE2, TRCK, ID3NoHeaderError
from mutagen.mp4 import MP4, MP4Cover
from mutagen.oggopus import OggOpus
from PIL import Image

log = logging.getLogger(__name__)

UA = {"User-Agent": "Mozilla/5.0 SaltMusic/0.2"}
MAX_IMAGE_BYTES = 15 * 1024 * 1024
# A cover is never bigger than this; refuse decompression bombs early.
Image.MAX_IMAGE_PIXELS = 40_000_000


@dataclass
class Tags:
    title: str
    artist: str
    album_artist: str
    album: str
    genre: str
    year: str = ""
    track: int | None = None
    total: int | None = None


def fetch(url: str, timeout: float = 15, limit: int = MAX_IMAGE_BYTES) -> bytes | None:
    """GET an http(s) URL, at most `limit` bytes; None on any failure."""
    if not url.lower().startswith(("https://", "http://")):
        return None  # no file:// or other schemes from metadata
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read(limit + 1)
    except Exception as e:
        log.debug("fetch %s: %s", url, e)
        return None
    return data if len(data) <= limit else None


def square_jpeg(data: bytes, max_size: int = 1200) -> bytes | None:
    """Center-crop to a square (video thumbnails are 16:9) and re-encode as JPEG."""
    try:
        img = Image.open(io.BytesIO(data))
        if img.width * img.height > Image.MAX_IMAGE_PIXELS:
            return None
        img = img.convert("RGB")
    except Exception:
        return None
    w, h = img.size
    side = min(w, h)
    img = img.crop(((w - side) // 2, (h - side) // 2, (w + side) // 2, (h + side) // 2))
    if side > max_size:
        img = img.resize((max_size, max_size), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, "JPEG", quality=92)
    return out.getvalue()


def cover_from(url: str | None, fallbacks: tuple[str, ...] = ()) -> bytes | None:
    for u in (url, *fallbacks):
        if u:
            raw = fetch(u)
            if raw:
                sq = square_jpeg(raw)
                if sq:
                    return sq
    return None


def _save(save, *args, **kwargs) -> None:
    """mutagen save, retried: on Windows an antivirus or the indexer may hold the
    fresh file open for a moment."""
    for attempt in range(6):
        try:
            save(*args, **kwargs)
            return
        except PermissionError:
            if attempt == 5:
                raise
            time.sleep(0.2 * (attempt + 1))


def write(path: Path, t: Tags, cover: bytes | None) -> None:
    ext = path.suffix.lower()
    if ext in (".opus", ".ogg"):
        _vorbis(OggOpus(path), t, cover)
    elif ext == ".flac":
        _vorbis(FLAC(path), t, cover)
    elif ext in (".m4a", ".mp4"):
        _mp4(path, t, cover)
    elif ext == ".mp3":
        _id3(path, t, cover)


def _picture(cover: bytes) -> Picture:
    pic = Picture()
    pic.type = 3  # front cover
    pic.mime = "image/jpeg"
    pic.desc = "Cover"
    pic.data = cover
    with Image.open(io.BytesIO(cover)) as im:
        pic.width, pic.height = im.size
    pic.depth = 24
    return pic


def _vorbis(f, t: Tags, cover: bytes | None) -> None:
    f["title"] = t.title
    f["artist"] = t.artist
    f["albumartist"] = t.album_artist
    f["album"] = t.album
    f["genre"] = t.genre
    if t.year:
        f["date"] = t.year
    if t.track:
        f["tracknumber"] = str(t.track)
    if t.total:
        f["tracktotal"] = str(t.total)
    if cover:
        pic = _picture(cover)
        if isinstance(f, FLAC):
            f.clear_pictures()
            f.add_picture(pic)
        else:
            f["metadata_block_picture"] = [base64.b64encode(pic.write()).decode("ascii")]
    _save(f.save)


def _mp4(path: Path, t: Tags, cover: bytes | None) -> None:
    f = MP4(path)
    f["\xa9nam"] = [t.title]
    f["\xa9ART"] = [t.artist]
    f["aART"] = [t.album_artist]
    f["\xa9alb"] = [t.album]
    f["\xa9gen"] = [t.genre]
    if t.year:
        f["\xa9day"] = [t.year]
    if t.track:
        f["trkn"] = [(t.track, t.total or 0)]
    if cover:
        f["covr"] = [MP4Cover(cover, imageformat=MP4Cover.FORMAT_JPEG)]
    _save(f.save)


def _id3(path: Path, t: Tags, cover: bytes | None) -> None:
    try:
        f = ID3(path)
    except ID3NoHeaderError:
        f = ID3()
    f.setall("TIT2", [TIT2(encoding=3, text=t.title)])
    f.setall("TPE1", [TPE1(encoding=3, text=t.artist)])
    f.setall("TPE2", [TPE2(encoding=3, text=t.album_artist)])
    f.setall("TALB", [TALB(encoding=3, text=t.album)])
    f.setall("TCON", [TCON(encoding=3, text=t.genre)])
    if t.year:
        f.setall("TDRC", [TDRC(encoding=3, text=t.year)])
    if t.track:
        f.setall("TRCK", [TRCK(encoding=3, text=f"{t.track}/{t.total}" if t.total else str(t.track))])
    if cover:
        f.delall("APIC")
        f.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=cover))
    _save(f.save, path, v2_version=3)


def read_cover(path: Path) -> bytes | None:
    """Embedded cover for the player; falls back to cover.jpg next to the file."""
    try:
        ext = path.suffix.lower()
        if ext in (".opus", ".ogg"):
            f = OggOpus(path)
            for b64 in f.get("metadata_block_picture", []):
                return Picture(base64.b64decode(b64)).data
        elif ext == ".flac":
            pics = FLAC(path).pictures
            if pics:
                return pics[0].data
        elif ext in (".m4a", ".mp4"):
            covr = MP4(path).get("covr")
            if covr:
                return bytes(covr[0])
        elif ext == ".mp3":
            for frame in ID3(path).getall("APIC"):
                return frame.data
    except Exception:
        pass
    side = path.parent / "cover.jpg"
    if side.exists():
        try:
            return side.read_bytes()
        except OSError:
            pass
    return None
