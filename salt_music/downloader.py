"""Download queue: resolves links, downloads with yt-dlp, tags, files into folders."""

from __future__ import annotations

import itertools
import json
import queue
import threading
import time
import traceback
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

import yt_dlp
from yt_dlp.utils import DownloadCancelled

from . import genre as genre_lookup
from . import library, metadata, naming, tagger
from .config import ARCHIVE_FILE, GENRES_FILE, JOBS_FILE, History, JsonStore, Settings, _write_json
from .links import Link

ACTIVE = ("queued", "running", "resolving")
JOBS_KEPT = 100

FORMAT_SELECT = {
    "opus": ("bestaudio[acodec=opus]/bestaudio", "opus"),
    "m4a": ("bestaudio[ext=m4a]/bestaudio[acodec^=mp4a]/bestaudio", "m4a"),
    "mp3": ("bestaudio", "mp3"),
    "flac": ("bestaudio", "flac"),
}
AUDIO_EXT = {".opus", ".m4a", ".mp3", ".flac", ".ogg"}
BOT_MARKERS = ("confirm you’re not a bot", "confirm you're not a bot", "Sign in to confirm")
COOKIE_MARKERS = ("cookies database", "could not copy", "Failed to decrypt", "keyring")


class BlockedByYouTube(RuntimeError):
    """Every next track would fail the same way: stop the whole job."""


@dataclass
class Item:
    release: metadata.Release
    track: metadata.Track
    folder: Path
    stem: str
    genre: str
    status: str = "queued"  # queued | downloading | processing | done | skipped | error | cancelled
    progress: float = 0.0
    speed: float | None = None
    eta: float | None = None
    started: float | None = None
    elapsed: float = 0.0
    error: str = ""
    path: Path | None = None
    artist_dir: Path | None = None
    artist: "metadata.ArtistInfo | None" = None


_ids = itertools.count(1)


@dataclass
class Job:
    link: Link
    title: str
    id: int = field(default_factory=lambda: next(_ids))
    status: str = "queued"  # queued | resolving | running | done | error | cancelled
    items: list[Item] = field(default_factory=list)
    error: str = ""
    resolved: bool = False
    started: float | None = None
    finished: float | None = None
    cancel: bool = False
    restored: dict[str, Item] = field(default_factory=dict)  # finished before a restart, by video id

    def count(self, *statuses: str) -> int:
        return sum(1 for i in self.items if i.status in statuses)

    @property
    def elapsed(self) -> float:
        if not self.started:
            return 0.0
        return (self.finished or time.monotonic()) - self.started

    def _avg(self) -> float | None:
        finished = [i for i in self.items if i.status == "done" and i.elapsed]
        return sum(i.elapsed for i in finished) / len(finished) if finished else None

    def _active_left(self, it: Item, avg: float | None) -> float | None:
        el = time.monotonic() - it.started if it.started else 0.0
        if avg is None:
            return it.eta if it.status == "downloading" else None
        # yt-dlp's eta covers the download only, the average also has conversion and tagging
        if avg > el:
            return max(avg - el, it.eta or 0.0)
        # slower than usual: only yt-dlp can tell, better no number than a wrong one
        return it.eta if it.status == "downloading" else None

    def item_left(self, it: Item) -> float | None:
        """Seconds until this track is ready (queued ones wait for those before them)."""
        avg = self._avg()
        if it.status in ("downloading", "processing"):
            return self._active_left(it, avg)
        if it.status != "queued" or avg is None:
            return None
        left = 0.0
        for other in self.items:
            if other.status in ("downloading", "processing"):
                left += self._active_left(other, avg) or 0.0
            elif other.status == "queued":
                left += avg
            if other is it:
                return left
        return None

    @property
    def eta(self) -> float | None:
        last = next((i for i in reversed(self.items) if i.status in ("queued", "downloading", "processing")), None)
        return self.item_left(last) if last else None


class Archive:
    """IDs that were already downloaded (yt-dlp archive file format)."""

    def __init__(self, path: Path = ARCHIVE_FILE):
        self.path = path
        self._lock = threading.Lock()
        try:
            self.ids = {line.split()[-1] for line in path.read_text("utf-8").splitlines() if line.strip()}
        except OSError:
            self.ids = set()

    def __contains__(self, vid: str) -> bool:
        return vid in self.ids

    def add(self, vid: str) -> None:
        with self._lock:
            if vid in self.ids:
                return
            self.ids.add(vid)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(f"youtube {vid}\n")

    def clear(self) -> None:
        with self._lock:
            self.ids.clear()
            self.path.unlink(missing_ok=True)


class Downloader:
    def __init__(
        self,
        settings: Settings,
        on_change: Callable[[Job | None], None],
        ask_genre: Callable[[str], str | None],
        on_file: Callable[[Path], None] | None = None,
    ):
        self.settings = settings
        self.on_change = on_change
        self.ask_genre = ask_genre
        self.on_file = on_file
        self.jobs: list[Job] = []
        self.history = History()
        self.archive = Archive()
        self.genres = JsonStore(GENRES_FILE)
        self.paused = threading.Event()
        self._queue: queue.Queue[Job] = queue.Queue()
        self._avatars_done: set[str] = set()
        self._lib_index: tuple[str, float, set[tuple[str, str]]] | None = None
        self._save_lock = threading.Lock()
        self._saved_at = 0.0
        self._load_jobs()
        self._worker = threading.Thread(target=self._run, daemon=True, name="salt-downloader")
        self._worker.start()

    # ---------- the list survives restarts ----------

    @property
    def busy(self) -> bool:
        return any(j.status in ACTIVE for j in self.jobs)

    def save_jobs(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._saved_at < 2:
            return
        self._saved_at = now
        data = [_job_to_dict(j) for j in list(self.jobs)[:JOBS_KEPT]]
        with self._save_lock:
            try:
                _write_json(JOBS_FILE, data)
            except OSError:
                pass

    def _load_jobs(self) -> None:
        try:
            raw = json.loads(JOBS_FILE.read_text("utf-8"))
        except (OSError, ValueError):
            return
        for d in raw:
            try:
                job = _job_from_dict(d)
            except (KeyError, TypeError, ValueError):
                continue
            self.jobs.append(job)
            if job.status == "queued":  # was unfinished when the app closed: carry on
                self._queue.put(job)

    # ---------- public API (called from UI) ----------

    def add(self, link: Link, title: str) -> Job:
        job = Job(link, title)
        self.jobs.insert(0, job)
        self._queue.put(job)
        self.on_change(job)
        return job

    def cancel(self, job: Job) -> None:
        job.cancel = True
        if job.status == "queued":
            job.status = "cancelled"
        self.on_change(job)

    def retry(self, job: Job) -> None:
        if not job.resolved:
            job.items.clear()  # resolving starts over and rebuilds them
        for it in job.items:
            if it.status in ("error", "cancelled"):
                it.status, it.error, it.progress = "queued", "", 0.0
        job.status, job.error, job.cancel = "queued", "", False
        job.finished = None
        self._queue.put(job)
        self.on_change(job)

    def retry_blocked(self) -> int:
        """Restart jobs that stopped on the bot check or unreadable cookies."""
        markers = BOT_MARKERS + COOKIE_MARKERS
        blocked = [j for j in self.jobs if j.status == "error"
                   and any(m in (j.error or "") for m in markers)]
        for j in blocked:
            self.retry(j)
        return len(blocked)

    def remove(self, job: Job) -> None:
        if job.status in ("running", "resolving"):
            return
        job.cancel = True
        if job in self.jobs:
            self.jobs.remove(job)
        self.on_change(None)

    def clear_finished(self) -> None:
        self.jobs = [j for j in self.jobs if j.status in ("queued", "running", "resolving")]
        self.on_change(None)

    def set_paused(self, paused: bool) -> None:
        if paused:
            self.paused.set()
        else:
            self.paused.clear()
        self.on_change(None)

    # ---------- worker ----------

    def _run(self) -> None:
        while True:
            job = self._queue.get()
            if job.cancel or job not in self.jobs:
                continue
            try:
                self._process(job)
            except DownloadCancelled:
                job.status = "cancelled"
            except BlockedByYouTube as e:
                job.status, job.error = "error", str(e)
                for it in job.items:
                    if it.status == "queued":
                        it.status, it.error = "error", str(e)
            except Exception as e:  # keep the worker alive
                traceback.print_exc()
                job.status, job.error = "error", _short(e)
            job.finished = time.monotonic()
            self.on_change(job)

    def _wait_if_paused(self, job: Job) -> None:
        while self.paused.is_set() and not job.cancel:
            time.sleep(0.2)
        if job.cancel:
            raise DownloadCancelled()

    def _process(self, job: Job) -> None:
        job.started = job.started or time.monotonic()
        s = self.settings
        if not job.resolved:
            job.status = "resolving"
            self.on_change(job)
            avatar_holder: list[metadata.ArtistInfo] = []
            for rel in metadata.resolve(job.link, s.include_videos, on_artist=avatar_holder.append):
                if job.cancel:
                    raise DownloadCancelled()
                if avatar_holder and job.title == job.link.url:
                    job.title = avatar_holder[0].name
                if job.title == job.link.url:
                    job.title = rel.title if job.link.kind != "track" else f"{rel.artist} — {rel.tracks[0].title}"
                new = self._prepare(rel, avatar_holder[0] if avatar_holder else None)
                for it in new:
                    old = job.restored.pop(it.track.video_id, None)
                    if old:
                        it.status, it.progress, it.path, it.elapsed = old.status, 1.0, old.path, old.elapsed
                job.items.extend(new)
                job.status = "running"
                self.on_change(job)
                self._download_items(job, new)
            job.resolved = True
        else:
            job.status = "running"
            self.on_change(job)
            self._download_items(job, [i for i in job.items if i.status == "queued"])

        if not job.items:
            job.status, job.error = "error", "nothing"
        elif job.count("error"):
            job.status = "error"
        else:
            job.status = "done"

    def _prepare(self, rel: metadata.Release, artist: metadata.ArtistInfo | None) -> list[Item]:
        s = self.settings
        if artist:
            # everything from one artist page lands in one folder, even when a release
            # credits the name differently (Молчат Дома / Molchat Doma)
            rel.artist, rel.artist_id = artist.name, artist.channel_id
        g = self._genre(rel.artist, rel.artist_id)
        values = {
            "genre": g,
            "artist": rel.artist,
            "album": rel.title,
            "year": rel.year,
            "type": rel.kind.upper() if rel.kind in ("ep",) else rel.kind.capitalize(),
        }
        template = s.templates.get(rel.kind) or s.templates["album"]
        base = Path(s.music_dir).expanduser()
        folder = naming.resolve_dir(base, naming.render(template, values))

        artist_dir = self._artist_dir(base, template, values)

        items = []
        for t in rel.tracks:
            numbered = rel.kind in ("album", "ep")
            fvals = {**values, "title": t.title,
                     "track": naming.track_number(t.number, rel.total) if numbered else ""}
            parts = naming.render(s.filename_template, fvals) or [naming.clean(t.title)]
            stem = naming.clean(" ".join(parts))
            items.append(Item(rel, t, folder, stem, g, artist_dir=artist_dir, artist=artist))
        return items

    def _artist_dir(self, base: Path, template: str, values: dict) -> Path | None:
        raw_parts = [p for p in template.replace("\\", "/").split("/") if p.strip()]
        for i, raw in enumerate(raw_parts):
            if "{artist}" in raw:
                return naming.resolve_dir(base, naming.render("/".join(raw_parts[: i + 1]), values))
        return None

    def _save_avatar(self, artist_dir: Path, rel: metadata.Release, artist: metadata.ArtistInfo | None) -> None:
        target = artist_dir / "artist.jpg"
        key = rel.artist_id or naming.key(rel.artist)
        if target.exists() or key in self._avatars_done:
            return
        self._avatars_done.add(key)
        url = artist.avatar_url if artist and artist.channel_id == rel.artist_id else None
        if not url and rel.artist_id:
            try:
                url = metadata.artist_info(rel.artist_id)[0].avatar_url
            except Exception:
                url = None
        data = tagger.cover_from(url)
        if data:
            artist_dir.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

    def _genre(self, artist: str, artist_id: str | None) -> str:
        s = self.settings
        if not s.auto_genre:
            if s.manual_genre.strip():
                return s.manual_genre.strip()
        key = artist_id or naming.key(artist)
        cached = self.genres.get(key)
        if cached and cached.get("genre"):
            return cached["genre"]
        g = genre_lookup.lookup(artist) if s.auto_genre else None
        if not g:
            g = (self.ask_genre(artist) or "").strip() or "Unknown Genre"
        self.genres.set(key, {"name": artist, "genre": g})
        return g

    def known_genres(self) -> list[tuple[str, str, str]]:
        """(key, artist name, genre) for every remembered artist."""
        out = []
        for k, v in dict(self.genres.data).items():
            if isinstance(v, dict):
                out.append((k, v.get("name", k), v.get("genre", "")))
        return sorted(out, key=lambda x: naming.key(x[1]))

    def set_artist_genre(self, key: str, name: str, value: str) -> None:
        self.genres.set(key, {"name": name, "genre": value.strip() or "Unknown Genre"})

    def _download_items(self, job: Job, items: list[Item]) -> None:
        covers: dict[int, bytes | None] = {}
        for n, it in enumerate(items):
            self._wait_if_paused(job)
            if it.status != "queued":
                continue
            if self._already_have(it):
                it.status = "skipped"
                it.progress = 1.0
                self.on_change(job)
                continue
            if n and self.settings.sleep_between > 0 and len(job.items) > 1:
                time.sleep(self.settings.sleep_between)
            rid = id(it.release)
            if rid not in covers:
                covers[rid] = tagger.cover_from(
                    it.release.cover_url,
                    (f"https://i.ytimg.com/vi/{it.track.video_id}/maxresdefault.jpg",
                     f"https://i.ytimg.com/vi/{it.track.video_id}/hqdefault.jpg"),
                )
            try:
                self._download_one(job, it, covers[rid])
                # Folder art only once something really landed in the folder.
                self._save_cover(it, covers[rid])
                if it.artist_dir is not None:
                    self._save_avatar(it.artist_dir, it.release, it.artist)
            except DownloadCancelled:
                it.status = "cancelled"
                self.on_change(job)
                raise
            except Exception as e:
                it.status, it.error = "error", _short(e)
                self._cleanup(it.folder)
                if any(m in it.error for m in BOT_MARKERS + COOKIE_MARKERS):
                    raise BlockedByYouTube(it.error)
            it.elapsed = time.monotonic() - (it.started or time.monotonic())
            self.on_change(job)

    def _save_cover(self, it: Item, cover: bytes | None) -> None:
        template = self.settings.templates.get(it.release.kind) or ""
        if not cover or "{album}" not in template:
            return
        target = it.folder / "cover.jpg"
        if not target.exists():
            it.folder.mkdir(parents=True, exist_ok=True)
            target.write_bytes(cover)

    def _cleanup(self, folder: Path) -> None:
        """Remove folders left empty by a failed download (up to the music dir)."""
        base = Path(self.settings.music_dir).expanduser()
        for leftover in folder.glob("*.part"):
            leftover.unlink(missing_ok=True)
        current = folder
        while current != base and base in current.parents:
            try:
                current.rmdir()
            except OSError:
                break
            current = current.parent

    def _already_have(self, it: Item) -> bool:
        if self.settings.skip_by_folder:
            return self._existing(it) or self._in_library(it)
        return it.track.video_id in self.archive or self._existing(it)

    def _library_index(self) -> set[tuple[str, str]]:
        # rescanned at most every 30 s: an artist page checks hundreds of tracks
        base = self.settings.music_dir
        if not self._lib_index or self._lib_index[0] != base or time.monotonic() - self._lib_index[1] > 30:
            self._lib_index = (base, time.monotonic(), library.index(Path(base)))
        return self._lib_index[2]

    def _in_library(self, it: Item) -> bool:
        """The same song anywhere in the music folder, whatever its file name."""
        title = naming.key(it.track.title)
        idx = self._library_index()
        return any((naming.key(a), title) in idx for a in (it.release.artist, *it.track.artists) if a)

    def _existing(self, it: Item) -> bool:
        if not it.folder.is_dir():
            return False
        want = naming.key(it.stem)
        for f in it.folder.iterdir():
            if f.suffix.lower() in AUDIO_EXT and naming.key(f.stem) == want:
                it.path = f
                self.archive.add(it.track.video_id)
                return True
        return False

    def _download_one(self, job: Job, it: Item, cover: bytes | None) -> None:
        s = self.settings
        fmt, codec = FORMAT_SELECT[s.audio_format]
        it.status, it.started, it.progress = "downloading", time.monotonic(), 0.0
        self.on_change(job)
        last = [0.0]

        def hook(d):
            if job.cancel:
                raise DownloadCancelled()
            while self.paused.is_set() and not job.cancel:
                time.sleep(0.2)
            if d["status"] == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate")
                if total:
                    it.progress = min(d.get("downloaded_bytes", 0) / total, 1.0)
                it.speed, it.eta = d.get("speed"), d.get("eta")
                now = time.monotonic()
                if now - last[0] > 0.25:
                    last[0] = now
                    self.on_change(job)
            elif d["status"] == "finished":
                it.progress, it.status, it.speed, it.eta = 1.0, "processing", None, None
                self.on_change(job)

        opts = {
            "format": fmt,
            "outtmpl": {"default": str(it.folder / it.stem).replace("%", "%%") + ".%(ext)s"},
            "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": codec, "preferredquality": "0"}],
            "progress_hooks": [hook],
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "retries": 5,
            "fragment_retries": 5,
            "overwrites": False,
        }
        if s.cookies_browser:
            opts["cookiesfrombrowser"] = (s.cookies_browser,)
        url = f"https://music.youtube.com/watch?v={it.track.video_id}"
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])

        path = it.folder / f"{it.stem}.{codec}"
        if not path.exists():
            raise RuntimeError("file not created")
        rel = it.release
        tagger.write(path, tagger.Tags(
            title=it.track.title,
            artist=", ".join(it.track.artists) or rel.artist,
            album_artist=rel.artist,
            album=rel.title if rel.kind not in ("track", "video") else it.track.title,
            genre=it.genre,
            year=rel.year,
            track=it.track.number if rel.kind in ("album", "ep") else None,
            total=rel.total if rel.kind in ("album", "ep") else None,
        ), cover)
        it.path, it.status = path, "done"
        self.archive.add(it.track.video_id)
        if self._lib_index:
            self._lib_index[2].update((naming.key(a), naming.key(it.track.title))
                                      for a in (rel.artist, *it.track.artists) if a)
        self.history.add({
            "title": it.track.title, "artist": rel.artist, "album": rel.title,
            "path": str(path), "time": time.time(),
        })
        if self.on_file:
            self.on_file(path)


LOGIN_COOKIES = {"SID", "SAPISID", "__Secure-3PSID", "__Secure-1PSID"}


def cookie_status(browser: str) -> str:
    """"ok" — signed in to YouTube, "anon" — cookies exist but no login, "error" — unreadable."""
    from yt_dlp.cookies import extract_cookies_from_browser

    class _Quiet:
        def debug(self, *a, **k): pass
        info = warning = error = debug

    try:
        jar = extract_cookies_from_browser(browser, logger=_Quiet())
    except Exception:
        return "error"
    names = {c.name for c in jar if c.domain.endswith(("youtube.com", "google.com"))}
    return "ok" if names & LOGIN_COOKIES else "anon"


def _job_to_dict(j: Job) -> dict:
    releases: list[dict] = []
    seen: dict[int, int] = {}
    items = []
    for it in list(j.items):
        r = it.release
        if id(r) not in seen:
            seen[id(r)] = len(releases)
            releases.append({k: getattr(r, k) for k in ("kind", "title", "artist", "artist_id", "year", "cover_url", "total")})
        items.append({
            "release": seen[id(r)], "track": asdict(it.track), "folder": str(it.folder), "stem": it.stem,
            "genre": it.genre, "status": it.status, "error": it.error, "elapsed": it.elapsed,
            "path": str(it.path) if it.path else None,
            "artist_dir": str(it.artist_dir) if it.artist_dir else None,
            "artist": asdict(it.artist) if it.artist else None,
        })
    return {"link": asdict(j.link), "title": j.title, "status": j.status, "error": j.error,
            "resolved": j.resolved, "elapsed": j.elapsed, "releases": releases, "items": items}


def _job_from_dict(d: dict) -> Job:
    now = time.monotonic()
    job = Job(Link(**d["link"]), d["title"], status=d["status"], error=d.get("error", ""),
              resolved=d.get("resolved", False))
    releases = [metadata.Release(**r) for r in d.get("releases", [])]
    for x in d.get("items", []):
        it = Item(releases[x["release"]], metadata.Track(**x["track"]), Path(x["folder"]), x["stem"], x["genre"],
                  status=x["status"], error=x.get("error", ""), elapsed=x.get("elapsed", 0.0))
        it.path = Path(x["path"]) if x.get("path") else None
        it.artist_dir = Path(x["artist_dir"]) if x.get("artist_dir") else None
        it.artist = metadata.ArtistInfo(**x["artist"]) if x.get("artist") else None
        if it.status in ("downloading", "processing"):
            it.status, it.progress = "queued", 0.0
        elif it.status in ("done", "skipped"):
            it.progress = 1.0
        job.items.append(it)
    job.started = now - d.get("elapsed", 0.0)
    if job.status in ACTIVE:
        job.status = "queued"
        if not job.resolved:
            # resolved again from scratch; tracks finished before keep their state
            job.restored = {i.track.video_id: i for i in job.items if i.status in ("done", "skipped")}
            job.items.clear()
    else:
        job.finished = now
    return job


def _short(e: Exception) -> str:
    msg = str(e).replace("ERROR: ", "").strip()
    first = msg.splitlines()[0] if msg else type(e).__name__
    return first[:300]
