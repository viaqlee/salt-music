"""Settings and small persistent stores (genre cache, history)."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from . import APP_NAME  # noqa: F401  (kept importable from here)
from .paths import CONFIG_DIR, DATA_DIR, IS_WINDOWS, default_music_dir

log = logging.getLogger(__name__)

SETTINGS_FILE = CONFIG_DIR / "settings.json"
GENRES_FILE = DATA_DIR / "artist_genres.json"
HISTORY_FILE = DATA_DIR / "history.json"
ARCHIVE_FILE = DATA_DIR / "archive.txt"
JOBS_FILE = DATA_DIR / "jobs.json"

# Release kinds that get their own path template.
KINDS = ("album", "ep", "single", "track", "video")

FORMATS = ("opus", "m4a", "mp3", "flac")
LANGUAGES = ("ru", "en")
# Only browsers yt-dlp can read. On Windows, Chrome and Edge encrypt cookies with
# app-bound keys and lock the database while running, so Firefox goes first.
if IS_WINDOWS:
    BROWSERS = ("", "firefox", "edge", "chrome", "brave", "opera", "vivaldi", "chromium", "whale")
else:
    BROWSERS = ("", "firefox", "chrome", "chromium", "brave", "edge", "opera", "vivaldi")

DEFAULT_TEMPLATES = {
    "album": "{genre}/{artist}/{album}",
    "ep": "{genre}/{artist}/{album}",
    "single": "{genre}/{artist}/Singles",
    "track": "{genre}/{artist}/Singles",
    "video": "{genre}/{artist}/Videos",
}
DEFAULT_FILENAME = "{track}. {title}"
PHONE_DIR = "/sdcard/Download/music"
MAX_SLEEP = 60.0


@dataclass
class Settings:
    language: str = "ru"
    music_dir: str = field(default_factory=lambda: str(default_music_dir()))
    audio_format: str = "opus"
    templates: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_TEMPLATES))
    filename_template: str = DEFAULT_FILENAME
    auto_genre: bool = True
    manual_genre: str = ""
    include_videos: bool = False
    background_on_close: bool = True  # closing the window hides it while downloads are running
    skip_by_folder: bool = False  # decide "already have it" by files on disk, not the download archive
    cookies_browser: str = ""
    cookies_file: str = ""  # cookies.txt exported from a browser; wins over cookies_browser
    sleep_between: float = 2.0
    phone_dir: str = PHONE_DIR
    phone_move: bool = False  # delete from the computer once the file is on the phone
    phone_covers: bool = True
    phone_auto: bool = False  # send new downloads right away while the phone is connected
    phone_address: str = ""  # host:port for wireless debugging
    phone_width: int = 320
    phone_open: bool = False
    left_width: int = 300
    right_width: int = 360
    left_open: bool = True
    right_open: bool = True

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        path = path or SETTINGS_FILE
        try:
            raw = json.loads(path.read_text("utf-8"))
        except (OSError, ValueError):
            return cls()
        return cls.from_dict(raw if isinstance(raw, dict) else {})

    @classmethod
    def from_dict(cls, raw: dict) -> "Settings":
        """Build settings from untrusted JSON: wrong types fall back to defaults."""
        s = cls()
        for f in fields(cls):
            if f.name not in raw:
                continue
            value = _coerce(raw[f.name], getattr(s, f.name))
            if value is not None:
                setattr(s, f.name, value)
        # Keep templates complete even if the file is from an older version.
        s.templates = {**DEFAULT_TEMPLATES,
                       **{k: v for k, v in s.templates.items() if k in KINDS and isinstance(v, str) and v.strip()}}
        if not s.filename_template.strip():
            s.filename_template = DEFAULT_FILENAME
        if s.audio_format not in FORMATS:
            s.audio_format = "opus"
        if s.language not in LANGUAGES:
            s.language = "ru"
        if s.cookies_browser not in BROWSERS:
            s.cookies_browser = ""
        if not s.music_dir.strip():
            s.music_dir = str(default_music_dir())
        if not s.phone_dir.startswith("/"):
            s.phone_dir = PHONE_DIR
        s.sleep_between = min(max(s.sleep_between, 0.0), MAX_SLEEP)
        s.phone_width = min(max(s.phone_width, 200), 900)
        s.left_width = min(max(s.left_width, 180), 900)
        s.right_width = min(max(s.right_width, 200), 900)
        return s

    def save(self, path: Path | None = None) -> None:
        _write_json(path or SETTINGS_FILE, asdict(self))


def _coerce(value, default):
    """`value` converted to the type of `default`, or None when it does not fit."""
    if isinstance(default, bool):
        return value if isinstance(value, bool) else None
    if isinstance(default, (int, float)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
            return None
        return type(default)(value)
    if isinstance(default, str):
        return value if isinstance(value, str) else None
    if isinstance(default, dict):
        return dict(value) if isinstance(value, dict) else None
    return None


def _write_json(path: Path, data) -> None:
    """Write atomically: readers see the old or the new file, never half of one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        # On Windows the target can be briefly locked by an antivirus or indexer.
        for attempt in range(5):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.05 * (attempt + 1))
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _read_json(path: Path, kind: type):
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return kind()
    if not isinstance(data, kind):
        log.warning("%s: unexpected content, starting empty", path.name)
        return kind()
    return data


class JsonStore:
    """Thread-safe dict persisted to a JSON file."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self.data: dict = _read_json(path, dict)

    def get(self, key, default=None):
        with self._lock:
            return self.data.get(key, default)

    def set(self, key, value) -> None:
        with self._lock:
            self.data[key] = value
            _write_json(self.path, self.data)


class History:
    """Last finished downloads, newest first."""

    LIMIT = 300

    def __init__(self, path: Path = HISTORY_FILE):
        self.path = path
        self._lock = threading.Lock()
        self.items: list[dict] = [i for i in _read_json(path, list) if isinstance(i, dict)]

    def add(self, item: dict) -> None:
        with self._lock:
            self.items.insert(0, item)
            del self.items[self.LIMIT:]
            _write_json(self.path, self.items)

    def clear(self) -> None:
        with self._lock:
            self.items = []
            _write_json(self.path, self.items)
