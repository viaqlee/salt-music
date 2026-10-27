"""External programs: where to find them and how to install them.

Lookup order: the program's own bin folder (the installer puts bundled tools
there), %LOCALAPPDATA%\\SaltMusic\\bin, the usual package-manager folders
(winget, scoop, chocolatey, Android SDK) and finally PATH. The current
directory is never searched: on Windows that would run whatever adb.exe
happens to lie in the folder the app was started from.
"""

from __future__ import annotations

import os
import shutil
import threading
import time
from pathlib import Path

from .paths import DATA_DIR, IS_WINDOWS, app_dir

FFMPEG, FFPROBE, DENO, MPV, ADB = "ffmpeg", "ffprobe", "deno", "mpv", "adb"

# shown in the UI next to "not found"
_HINTS_WINDOWS = {
    FFMPEG: "winget install Gyan.FFmpeg",
    DENO: "winget install DenoLand.Deno",
    ADB: "winget install Google.PlatformTools",
    MPV: "winget install shinchiro.mpv",
}
_HINTS_LINUX = {
    FFMPEG: "sudo pacman -S ffmpeg",
    DENO: "sudo pacman -S deno",
    ADB: "sudo pacman -S android-tools",
    MPV: "sudo pacman -S mpv",
}


def install_hint(name: str) -> str:
    return (_HINTS_WINDOWS if IS_WINDOWS else _HINTS_LINUX).get(name, name)


def search_dirs() -> list[Path]:
    dirs = [app_dir() / "bin", DATA_DIR / "bin"]
    if IS_WINDOWS:
        local = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        program_data = Path(os.environ.get("ProgramData") or r"C:\ProgramData")
        dirs += [
            local / "Microsoft" / "WinGet" / "Links",
            Path.home() / "scoop" / "shims",
            program_data / "chocolatey" / "bin",
            local / "Android" / "Sdk" / "platform-tools",
            Path.home() / ".deno" / "bin",
        ]
    return dirs


def _candidates(name: str) -> list[str]:
    return [name + ".exe", name] if IS_WINDOWS else [name]


# Found paths are kept; a missing tool is looked for again after MISS_TTL seconds,
# so one installed while the app runs shows up without a restart.
MISS_TTL = 10.0
_found: dict[str, str] = {}
_missed: dict[str, float] = {}
_lock = threading.Lock()


def _search(name: str) -> str | None:
    for folder in search_dirs():
        for fname in _candidates(name):
            p = folder / fname
            if p.is_file():
                return str(p)
    found = shutil.which(name)
    if found and Path(found).is_absolute():
        return found
    return None


def find(name: str) -> str | None:
    """Absolute path of an external program, or None."""
    with _lock:
        if name in _found:
            return _found[name]
        if time.monotonic() - _missed.get(name, -MISS_TTL) < MISS_TTL:
            return None
    path = _search(name)
    with _lock:
        if path:
            _found[name] = path
            _missed.pop(name, None)
        else:
            _missed[name] = time.monotonic()
    return path


def refresh() -> None:
    """Forget cached lookups (after the user installed something)."""
    with _lock:
        _found.clear()
        _missed.clear()
    setup_path()


def available(name: str) -> bool:
    return find(name) is not None


def setup_path() -> None:
    """Make our tool folders visible to libraries that search PATH themselves (yt-dlp)."""
    if IS_WINDOWS:
        # CreateProcess and shutil.which look into the current directory first unless told not to
        os.environ["NoDefaultCurrentDirectoryInExePath"] = "1"
    current = os.environ.get("PATH", "").split(os.pathsep)
    extra = [str(d) for d in search_dirs() if d.is_dir() and str(d) not in current]
    if extra:
        os.environ["PATH"] = os.pathsep.join([*extra, *current])

