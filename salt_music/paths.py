"""Where the app keeps its files, per platform.

Windows: settings in %APPDATA%\\SaltMusic, everything else in %LOCALAPPDATA%\\SaltMusic.
Linux:   $XDG_CONFIG_HOME/salt-music and $XDG_DATA_HOME/salt-music.
SALT_MUSIC_HOME puts both under one folder (portable copy, tests).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"
FROZEN = bool(getattr(sys, "frozen", False))

# Windows known folder id of the user's Music library (may be redirected to OneDrive).
_FOLDERID_MUSIC = "{4BD8D571-6D19-48D3-BE97-422220080E43}"


def _dirs() -> tuple[Path, Path]:
    home = os.environ.get("SALT_MUSIC_HOME")
    if home:
        root = Path(home).expanduser()
        return root / "config", root / "data"
    if IS_WINDOWS:
        roaming = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        local = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return roaming / "SaltMusic", local / "SaltMusic"
    config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    data = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return config / "salt-music", data / "salt-music"


CONFIG_DIR, DATA_DIR = _dirs()
LOG_DIR = DATA_DIR / "logs"
PACKAGES_DIR = DATA_DIR / "packages"  # yt-dlp updates installed by the app itself


def app_dir() -> Path:
    """Folder of the program: next to the .exe when packed, the project root otherwise."""
    if FROZEN:
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def assets_dir() -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass and (Path(meipass) / "assets").is_dir():
        return Path(meipass) / "assets"
    return app_dir() / "assets"


def _known_music_folder() -> Path | None:
    if not IS_WINDOWS:
        return None
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("d1", wintypes.DWORD), ("d2", wintypes.WORD), ("d3", wintypes.WORD), ("d4", ctypes.c_ubyte * 8)]

    try:
        guid = GUID()
        ctypes.oledll.ole32.CLSIDFromString(_FOLDERID_MUSIC, ctypes.byref(guid))
        out = ctypes.c_wchar_p()
        ctypes.oledll.shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(out))
        try:
            return Path(out.value) if out.value else None
        finally:
            ctypes.windll.ole32.CoTaskMemFree(out)
    except OSError:
        return None


def default_music_dir() -> Path:
    return _known_music_folder() or Path.home() / "Music"
