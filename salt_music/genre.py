"""Genre lookup: YouTube Music has none, so ask MusicBrainz, then Deezer."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "SaltMusic/0.1 (desktop music organizer)"
_last_mb = 0.0


def _get(url: str, timeout: float = 10, retries: int = 2) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            # 503 = MusicBrainz rate limit; wait and retry.
            if e.code != 503 or attempt == retries:
                raise
            time.sleep(2 + attempt * 2)
    return {}


def _norm(s: str) -> str:
    return "".join(ch for ch in s.casefold() if ch.isalnum())


def musicbrainz(artist: str) -> str | None:
    global _last_mb
    # MusicBrainz allows ~1 request per second.
    wait = 1.1 - (time.monotonic() - _last_mb)
    if wait > 0:
        time.sleep(wait)
    q = urllib.parse.quote(f'artist:"{artist}"')
    data = _get(f"https://musicbrainz.org/ws/2/artist/?query={q}&fmt=json&limit=5")
    _last_mb = time.monotonic()
    want = _norm(artist)
    for a in data.get("artists", []):
        if _norm(a.get("name", "")) != want and a.get("score", 0) < 95:
            continue
        time.sleep(1.1)
        full = _get(f"https://musicbrainz.org/ws/2/artist/{a['id']}?inc=genres+tags&fmt=json")
        _last_mb = time.monotonic()
        ranked = sorted(full.get("genres") or full.get("tags") or [], key=lambda g: -g.get("count", 0))
        if ranked:
            return ranked[0]["name"].title()
        break
    return None


def deezer(artist: str) -> str | None:
    q = urllib.parse.quote(artist)
    found = _get(f"https://api.deezer.com/search/artist?q={q}&limit=5").get("data") or []
    want = _norm(artist)
    # Several artists can share a name: take the most popular one.
    same = [a for a in found if _norm(a.get("name", "")) == want]
    match = max(same, key=lambda a: a.get("nb_fan", 0), default=None)
    if not match:
        return None
    albums = _get(f"https://api.deezer.com/artist/{match['id']}/albums?limit=10").get("data") or []
    counts: dict[int, int] = {}
    for al in albums:
        gid = al.get("genre_id")
        if gid and gid > 0:
            counts[gid] = counts.get(gid, 0) + 1
    if not counts:
        return None
    gid = max(counts, key=counts.get)
    return _get(f"https://api.deezer.com/genre/{gid}").get("name") or None


def lookup(artist: str) -> str | None:
    for source in (musicbrainz, deezer):
        try:
            g = source(artist)
        except Exception:
            g = None
        if g:
            return g.strip()
    return None
