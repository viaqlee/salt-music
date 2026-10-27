"""Resolve links into releases with full YouTube Music metadata (via ytmusicapi).

yt-dlp can't read YouTube Music artist pages (it redirects to the plain YouTube
channel, losing albums/singles), so discography and tags come from ytmusicapi
and yt-dlp only downloads the audio.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from typing import Callable, Iterator

from ytmusicapi import YTMusic

from .links import Link


@dataclass
class Track:
    video_id: str
    title: str
    artists: list[str]
    number: int | None = None
    duration: int | None = None


@dataclass
class Release:
    kind: str  # album | ep | single | track | video
    title: str
    artist: str  # album artist: decides the folder
    artist_id: str | None
    year: str = ""
    cover_url: str | None = None
    total: int = 0
    tracks: list[Track] = field(default_factory=list)


@dataclass
class ArtistInfo:
    name: str
    channel_id: str
    avatar_url: str | None = None


_local = threading.local()


def api() -> YTMusic:
    # YTMusic holds a requests session; keep one per thread.
    if not hasattr(_local, "yt"):
        _local.yt = YTMusic()
    return _local.yt


def big_thumb(thumbs, size: int = 1200) -> str | None:
    if not thumbs:
        return None
    url = max(thumbs, key=lambda t: t.get("width", 0) or 0)["url"]
    if "googleusercontent.com" in url or "ggpht.com" in url:
        url = re.sub(r"=w\d+-h\d+[^&?]*$", f"=w{size}-h{size}-l90-rj", url)
    return url


def classify(album_type: str | None, count: int) -> str:
    t = (album_type or "").lower()
    if count <= 1 or t == "single":
        return "single"
    if t == "ep":
        return "ep"
    return "album"


def _names(artists) -> list[str]:
    return [a["name"] for a in (artists or []) if a.get("name")]


def get_album(browse_id: str, only: set[str] | None = None) -> Release:
    yt = api()
    if browse_id.startswith("OLAK5uy_"):
        browse_id = yt.get_album_browse_id(browse_id)
    al = yt.get_album(browse_id)
    album_artists = al.get("artists") or []
    main = album_artists[0] if album_artists else {"name": "Various Artists", "id": None}
    available = [t for t in al.get("tracks", []) if t.get("videoId")]
    rel = Release(
        kind=classify(al.get("type"), len(available) or al.get("trackCount") or 0),
        title=al.get("title") or "Unknown Album",
        artist=main.get("name") or "Unknown Artist",
        artist_id=main.get("id"),
        year=str(al.get("year") or ""),
        cover_url=big_thumb(al.get("thumbnails")),
        total=len(al.get("tracks", [])),
    )
    for i, t in enumerate(al.get("tracks", []), 1):
        vid = t.get("videoId")
        if not vid or (only is not None and vid not in only):
            continue
        rel.tracks.append(Track(
            video_id=vid,
            title=t.get("title") or vid,
            artists=_names(t.get("artists")) or [rel.artist],
            number=t.get("trackNumber") or i,
            duration=t.get("duration_seconds"),
        ))
    return rel


def resolve_artist_id(handle: str) -> str:
    """@handle -> UC... channel id (through yt-dlp, ytmusicapi can't)."""
    import yt_dlp

    from .logs import YtdlpLogger

    opts = {"quiet": True, "no_warnings": True, "extract_flat": True, "playlist_items": "0",
            "skip_download": True, "logger": YtdlpLogger()}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"https://www.youtube.com/{handle}", download=False, process=False)
    cid = info.get("channel_id") or info.get("id")
    if not cid or not cid.startswith("UC"):
        raise LookupError("channel not found")
    return cid


def artist_info(channel_id: str) -> tuple[ArtistInfo, dict]:
    yt = api()
    try:
        a = yt.get_artist(channel_id)
    except KeyError:
        # a regular YouTube channel, not a YT Music artist page
        raise LookupError("err_not_artist") from None
    name = a.get("name") or "Unknown Artist"
    avatar = None
    try:
        for r in yt.search(name, filter="artists", limit=10):
            if r.get("browseId") == channel_id:
                avatar = big_thumb(r.get("thumbnails"))
                break
    except Exception:
        pass
    return ArtistInfo(name, channel_id, avatar or big_thumb(a.get("thumbnails"))), a


def artist_releases(raw: dict, include_videos: bool, seen: set[str]) -> Iterator[Release]:
    """Yield every album / EP / single of an artist; each track only once."""
    yt = api()
    browse_ids: list[str] = []
    for section in ("albums", "singles"):
        sec = raw.get(section) or {}
        items = sec.get("results") or []
        if sec.get("browseId") and sec.get("params"):
            try:
                items = yt.get_artist_albums(sec["browseId"], sec["params"], limit=None)
            except Exception:
                pass
        for it in items:
            bid = it.get("browseId")
            if bid and bid not in browse_ids:
                browse_ids.append(bid)

    for bid in browse_ids:
        rel = get_album(bid)
        rel.tracks = [t for t in rel.tracks if t.video_id not in seen]
        seen.update(t.video_id for t in rel.tracks)
        if rel.tracks:
            yield rel

    if include_videos:
        vids = raw.get("videos") or {}
        pid = vids.get("browseId")
        if pid:
            pl = yt.get_playlist(pid.removeprefix("VL"), limit=None)
            rel = Release("video", "Videos", raw.get("name") or "Unknown Artist", raw.get("channelId"))
            for t in pl.get("tracks", []):
                vid = t.get("videoId")
                if vid and vid not in seen:
                    seen.add(vid)
                    rel.tracks.append(Track(vid, t.get("title") or vid, _names(t.get("artists")) or [rel.artist],
                                            duration=t.get("duration_seconds")))
            if rel.tracks:
                yield rel


def single_track(video_id: str) -> Release:
    """A lone track: placed into its album when YouTube Music knows one."""
    yt = api()
    w = yt.get_watch_playlist(video_id, limit=1)
    tracks = w.get("tracks") or []
    t = tracks[0] if tracks else {}
    album = t.get("album") or {}
    if album.get("id"):
        try:
            rel = get_album(album["id"], only={video_id})
            if rel.tracks:
                return rel
        except Exception:
            pass
    artists = t.get("artists") or []
    main = artists[0] if artists else {"name": "Unknown Artist", "id": None}
    rel = _album_of_video(video_id, t.get("title") or "", main.get("name") or "")
    if rel:
        return rel
    return Release(
        kind="track",
        title=t.get("title") or video_id,
        artist=main.get("name") or "Unknown Artist",
        artist_id=main.get("id"),
        year=str(t.get("year") or ""),
        cover_url=f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg",
        total=1,
        tracks=[Track(video_id, t.get("title") or video_id, _names(artists) or [main.get("name") or "Unknown Artist"])],
    )


def _album_of_video(video_id: str, title: str, artist: str) -> Release | None:
    """Music videos have no album: find the same song among album tracks."""
    if not title or not artist:
        return None
    clean = lambda s: re.sub(r"\s*[\(\[](official|music|video|lyric|audio|hd|4k|remaster)[^\)\]]*[\)\]]", "", s, flags=re.I)
    want = _key(clean(title))
    try:
        results = api().search(f"{artist} {clean(title)}", filter="songs", limit=5)
    except Exception:
        return None
    for r in results:
        if _key(r.get("title") or "") != want or _key(artist) not in {_key(n) for n in _names(r.get("artists"))}:
            continue
        aid = (r.get("album") or {}).get("id")
        if aid and r.get("videoId"):
            try:
                # The album may list the very same video id, or the audio-only one.
                rel = get_album(aid, only={r["videoId"], video_id})
                own = [t for t in rel.tracks if t.video_id == video_id]
                rel.tracks = own or rel.tracks[:1]
                if rel.tracks:
                    return rel
            except Exception:
                return None
    return None


def _key(s: str) -> str:
    return "".join(ch for ch in s.casefold() if ch.isalnum())


def playlist_releases(pid: str, seen: set[str]) -> Iterator[Release]:
    yt = api()
    pl = yt.get_playlist(pid, limit=None)
    by_album: dict[str, set[str]] = {}
    loose: list[str] = []
    for t in pl.get("tracks", []):
        vid = t.get("videoId")
        if not vid or vid in seen:
            continue
        seen.add(vid)
        aid = (t.get("album") or {}).get("id")
        if aid:
            by_album.setdefault(aid, set()).add(vid)
        else:
            loose.append(vid)
    for aid, vids in by_album.items():
        try:
            yield get_album(aid, only=vids)
        except Exception:
            loose.extend(vids)
    for vid in loose:
        yield single_track(vid)


def resolve(link: Link, include_videos: bool, on_artist: Callable[[ArtistInfo], None] | None = None) -> Iterator[Release]:
    seen: set[str] = set()
    if link.kind == "album":
        yield get_album(link.id)
    elif link.kind == "track":
        yield single_track(link.id)
    elif link.kind == "playlist":
        yield from playlist_releases(link.id, seen)
    elif link.kind == "artist":
        cid = link.id if link.id.startswith("UC") else resolve_artist_id(link.id)
        info, raw = artist_info(cid)
        if on_artist:
            on_artist(info)
        yield from artist_releases(raw, include_videos, seen)


def search(query: str, limit: int = 6) -> list[dict]:
    """Quick search for the link field: songs, albums and artists."""
    yt = api()
    out = []
    for r in yt.search(query, limit=limit):
        rt = r.get("resultType")
        artists = ", ".join(_names(r.get("artists")))
        if rt == "song" and r.get("videoId"):
            out.append({"kind": "track", "id": r["videoId"], "title": r.get("title"), "sub": artists,
                        "url": f"https://music.youtube.com/watch?v={r['videoId']}"})
        elif rt == "album" and r.get("browseId"):
            out.append({"kind": "album", "id": r["browseId"], "title": r.get("title"), "sub": " · ".join(x for x in (r.get('type'), artists) if x),
                        "url": f"https://music.youtube.com/browse/{r['browseId']}"})
        elif rt == "artist":
            # the top result keeps the id in artists[0] instead of browseId
            first = (r.get("artists") or [{}])[0]
            cid = r.get("browseId") or first.get("id")
            if cid and all(o["id"] != cid for o in out):
                out.append({"kind": "artist", "id": cid, "title": r.get("artist") or first.get("name") or r.get("title"),
                            "sub": "", "url": f"https://music.youtube.com/channel/{cid}"})
    return out[: limit * 2]
