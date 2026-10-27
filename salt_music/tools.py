"""External programs: where to find them and how to install them.

Lookup order:
1. the path the user set in the settings (a file, or a folder holding the program);
2. the program's own bin folder (the installer puts bundled tools there) and
   DATA_DIR/bin;
3. the usual install places: on Windows winget (its Links folders and the
   unpacked packages), scoop, chocolatey, the Android SDK, Program Files; on
   Linux ~/.local/bin, /usr/local/bin, /usr/bin, the Android SDK and so on;
4. PATH. On Windows the PATH saved in the registry is read too: a program
   installed while Salt Music (or the setup that started it) was running is not
   in our inherited PATH yet.

The current directory is never searched: on Windows that would run whatever
adb.exe happens to lie in the folder the app was started from.
"""

from __future__ import annotations

import os
import shutil
import threading
import time
from pathlib import Path

from .paths import DATA_DIR, IS_WINDOWS, app_dir

FFMPEG, FFPROBE, DENO, MPV, ADB = "ffmpeg", "ffprobe", "deno", "mpv", "adb"
# the ones a user can point to in the settings; ffprobe follows ffmpeg
CONFIGURABLE = (FFMPEG, DENO, MPV, ADB)

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


# ---------- where to look ----------

def _registry_path() -> list[Path]:
    """Windows: PATH as saved for the user and the machine, with %VARS% expanded."""
    import winreg

    out: list[Path] = []
    keys = ((winreg.HKEY_CURRENT_USER, r"Environment"),
            (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"))
    for root, sub in keys:
        try:
            with winreg.OpenKey(root, sub) as k:
                value, _ = winreg.QueryValueEx(k, "Path")
        except OSError:
            continue
        for part in str(value).split(";"):
            part = os.path.expandvars(part.strip().strip('"'))
            if part and os.path.isabs(part):
                out.append(Path(part))
    return out


# winget unpacks zip packages to Packages\<Id>_<source>\<version folder>\[bin\]tool.exe
_PACKAGE_DEPTH = 3


def _winget_package_dirs(root: Path) -> list[Path]:
    found: list[Path] = []
    try:
        packages = [p for p in root.iterdir() if p.is_dir()]
    except OSError:
        return found
    wanted = {n + ".exe" for n in (*CONFIGURABLE, FFPROBE)}
    for pkg in packages:
        stack = [(pkg, 0)]
        while stack:
            folder, depth = stack.pop()
            try:
                entries = list(os.scandir(folder))
            except OSError:
                continue
            if any(e.is_file() and e.name.lower() in wanted for e in entries):
                found.append(folder)
            if depth < _PACKAGE_DEPTH:
                stack += [(Path(e.path), depth + 1) for e in entries if e.is_dir(follow_symlinks=False)]
    return found


def _windows_dirs() -> list[Path]:
    local = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    program_files = Path(os.environ.get("ProgramFiles") or r"C:\Program Files")
    program_data = Path(os.environ.get("ProgramData") or r"C:\ProgramData")
    return [
        local / "Microsoft" / "WinGet" / "Links",
        program_files / "WinGet" / "Links",
        *_winget_package_dirs(local / "Microsoft" / "WinGet" / "Packages"),
        *_winget_package_dirs(program_files / "WinGet" / "Packages"),
        Path.home() / "scoop" / "shims",
        program_data / "scoop" / "shims",
        program_data / "chocolatey" / "bin",
        local / "Android" / "Sdk" / "platform-tools",
        Path.home() / ".deno" / "bin",
        program_files / "ffmpeg" / "bin",
        Path("C:/ffmpeg/bin"),
        program_files / "mpv",
        local / "Programs" / "mpv",
        *_registry_path(),
    ]


def _linux_dirs() -> list[Path]:
    home = Path.home()
    # a launcher started from the desktop menu often has a short PATH without these
    return [
        home / ".local" / "bin",
        home / ".deno" / "bin",
        home / "bin",
        Path("/usr/local/bin"),
        Path("/usr/bin"),
        Path("/bin"),
        home / "Android" / "Sdk" / "platform-tools",
        Path("/opt/android-sdk/platform-tools"),
        Path("/snap/bin"),
    ]


def search_dirs() -> list[Path]:
    dirs = [app_dir() / "bin", DATA_DIR / "bin"]
    dirs += _windows_dirs() if IS_WINDOWS else _linux_dirs()
    return dirs


def _candidates(name: str) -> list[str]:
    return [name + ".exe", name] if IS_WINDOWS else [name]


def _runnable(p: Path) -> bool:
    try:
        return p.is_file() and (IS_WINDOWS or os.access(p, os.X_OK))
    except OSError:
        return False


# ---------- paths set by the user ----------

_custom: dict[str, str] = {}


def set_custom(paths: dict[str, str]) -> None:
    """Paths from the settings: {"ffmpeg": "C:\\...\\ffmpeg.exe" or a folder, ...}."""
    with _lock:
        _custom.clear()
        _custom.update({k: v.strip() for k, v in paths.items() if k in CONFIGURABLE and v and v.strip()})
    refresh()


def _in_folder(folder: Path, name: str) -> Path | None:
    for fname in _candidates(name):
        p = folder / fname
        if _runnable(p):
            return p
    # unpacked archives keep the programs one level down, in bin
    for fname in _candidates(name):
        p = folder / "bin" / fname
        if _runnable(p):
            return p
    return None


def custom_status(name: str) -> tuple[str, str | None]:
    """(what the user set, the program it resolves to or None). ("", None) when nothing is set."""
    owner = FFMPEG if name == FFPROBE else name
    with _lock:
        raw = _custom.get(owner, "")
    if not raw:
        return "", None
    p = Path(os.path.expandvars(os.path.expanduser(raw)))
    if not p.is_absolute():  # relative paths would depend on the current folder
        return raw, None
    if name == FFPROBE:  # ffprobe lives next to the ffmpeg the user chose
        folder = p.parent if p.is_file() else p
        found = _in_folder(folder, FFPROBE)
        return raw, str(found) if found else None
    if p.is_dir():
        found = _in_folder(p, name)
        return raw, str(found) if found else None
    return raw, str(p) if _runnable(p) else None


# ---------- lookup ----------

# Found paths are kept; a missing tool is looked for again after MISS_TTL seconds,
# so one installed while the app runs shows up without a restart.
MISS_TTL = 10.0
_found: dict[str, str] = {}
_missed: dict[str, float] = {}
_lock = threading.RLock()


def _search(name: str) -> str | None:
    raw, custom = custom_status(name)
    if custom:
        return custom
    for folder in search_dirs():
        for fname in _candidates(name):
            p = folder / fname
            if _runnable(p):
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


_added: list[str] = []  # what setup_path() put on PATH last time


def setup_path() -> None:
    """Make our tool folders visible to libraries that search PATH themselves (yt-dlp)."""
    global _added
    if IS_WINDOWS:
        # CreateProcess and shutil.which look into the current directory first unless told not to
        os.environ["NoDefaultCurrentDirectoryInExePath"] = "1"
    # a folder the user chose before and then dropped must not stay on PATH
    current = [d for d in os.environ.get("PATH", "").split(os.pathsep) if d and d not in _added]
    extra: list[str] = []
    for name in CONFIGURABLE:
        _, custom = custom_status(name)
        if custom:
            extra.append(str(Path(custom).parent))
    extra += [str(d) for d in search_dirs() if d.is_dir()]
    extra = list(dict.fromkeys(d for d in extra if d not in current))
    _added = extra
    os.environ["PATH"] = os.pathsep.join([*extra, *current])
