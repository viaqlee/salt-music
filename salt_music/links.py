"""Validate and normalise YouTube / YouTube Music links."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

HOSTS = {
    "youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com",
    "youtu.be", "www.youtu.be", "youtube-nocookie.com", "www.youtube-nocookie.com",
}
VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
CHANNEL_ID = re.compile(r"^UC[A-Za-z0-9_-]{22}$")


@dataclass(frozen=True)
class Link:
    kind: str  # "track" | "album" | "playlist" | "artist"
    id: str
    url: str


class LinkError(ValueError):
    """Raised with an i18n key describing why the link is rejected."""


def parse(text: str) -> Link:
    text = (text or "").strip()
    if not text:
        raise LinkError("err_link_empty")
    if not re.match(r"^https?://", text, re.I):
        text = "https://" + text
    try:
        u = urlparse(text)
    except ValueError:
        raise LinkError("err_link_bad")
    host = (u.hostname or "").lower()
    if host not in HOSTS:
        raise LinkError("err_link_host")
    qs = parse_qs(u.query)
    path = u.path.rstrip("/")

    if host.endswith("youtu.be"):
        vid = path.lstrip("/")
        if VIDEO_ID.match(vid):
            return _track(vid)
        raise LinkError("err_link_bad")

    # Album pages: music.youtube.com/browse/MPREb_...
    m = re.match(r"^/browse/(MPREb_[A-Za-z0-9_-]+)$", path)
    if m:
        return Link("album", m.group(1), f"https://music.youtube.com/browse/{m.group(1)}")

    m = re.match(r"^/channel/(UC[A-Za-z0-9_-]{22})", path)
    if m:
        return _artist(m.group(1))
    m = re.match(r"^/browse/(UC[A-Za-z0-9_-]{22})$", path)
    if m:
        return _artist(m.group(1))
    m = re.match(r"^/(@[^/]+)", path)
    if m:
        # Handle (@name): resolved to a channel id later by the metadata layer.
        return Link("artist", m.group(1), f"https://www.youtube.com/{m.group(1)}")

    if path in ("/watch", "") and "v" in qs and VIDEO_ID.match(qs["v"][0]):
        return _track(qs["v"][0])
    m = re.match(r"^/(?:shorts|embed|live|v)/([A-Za-z0-9_-]{11})$", path)
    if m:
        return _track(m.group(1))

    if path == "/playlist" and "list" in qs:
        return _playlist(qs["list"][0])
    m = re.match(r"^/browse/VL([A-Za-z0-9_-]+)$", path)
    if m:
        return _playlist(m.group(1))

    raise LinkError("err_link_bad")


def _track(vid: str) -> Link:
    return Link("track", vid, f"https://music.youtube.com/watch?v={vid}")


def _artist(cid: str) -> Link:
    return Link("artist", cid, f"https://music.youtube.com/channel/{cid}")


def _playlist(pid: str) -> Link:
    if not re.match(r"^[A-Za-z0-9_-]{10,}$", pid):
        raise LinkError("err_link_bad")
    # Auto-generated album playlists (OLAK5uy_) are albums.
    kind = "album" if pid.startswith("OLAK5uy_") else "playlist"
    return Link(kind, pid, f"https://music.youtube.com/playlist?list={pid}")
