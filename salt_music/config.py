"""Settings, app paths and small persistent stores (genre cache, history)."""

from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

APP_NAME = "Salt Music"

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "salt-music"
DATA_DIR = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "salt-music"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
GENRES_FILE = DATA_DIR / "artist_genres.json"
HISTORY_FILE = DATA_DIR / "history.json"
ARCHIVE_FILE = DATA_DIR / "archive.txt"
JOBS_FILE = DATA_DIR / "jobs.json"

# Release kinds that get their own path template.
KINDS = ("album", "ep", "single", "track", "video")

FORMATS = ("opus", "m4a", "mp3", "flac")
BROWSERS = ("", "firefox", "chrome", "chromium", "brave", "edge", "opera", "vivaldi", "librewolf", "zen")

DEFAULT_TEMPLATES = {
    "album": "{genre}/{artist}/{album}",
    "ep": "{genre}/{artist}/{album}",
    "single": "{genre}/{artist}/Singles",
    "track": "{genre}/{artist}/Singles",
    "video": "{genre}/{artist}/Videos",
}
DEFAULT_FILENAME = "{track}. {title}"
PHONE_DIR = "/sdcard/Download/music"


@dataclass
class Settings:
    language: str = "ru"
    music_dir: str = str(Path.home() / "Music")
    audio_format: str = "opus"
    templates: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_TEMPLATES))
    filename_template: str = DEFAULT_FILENAME
    auto_genre: bool = True
    manual_genre: str = ""
    include_videos: bool = False
    background_on_close: bool = True  # closing the window hides it while downloads are running
    skip_by_folder: bool = False  # decide "already have it" by files on disk, not the download archive
    cookies_browser: str = ""
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
    def load(cls) -> "Settings":
        try:
            raw = json.loads(SETTINGS_FILE.read_text("utf-8"))
        except (OSError, ValueError):
            return cls()
        known = {f.name for f in fields(cls)}
        s = cls(**{k: v for k, v in raw.items() if k in known})
        # Keep templates complete even if the file is from an older version.
        s.templates = {**DEFAULT_TEMPLATES, **(s.templates or {})}
        if s.audio_format not in FORMATS:
            s.audio_format = "opus"
        return s

    def save(self) -> None:
        _write_json(SETTINGS_FILE, asdict(self))


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
    tmp.replace(path)


class JsonStore:
    """Thread-safe dict persisted to a JSON file."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        try:
            self.data = json.loads(path.read_text("utf-8"))
        except (OSError, ValueError):
            self.data = {}

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
        try:
            self.items: list[dict] = json.loads(path.read_text("utf-8"))
        except (OSError, ValueError):
            self.items = []

    def add(self, item: dict) -> None:
        with self._lock:
            self.items.insert(0, item)
            del self.items[self.LIMIT:]
            _write_json(self.path, self.items)

    def clear(self) -> None:
        with self._lock:
            self.items = []
            _write_json(self.path, self.items)
