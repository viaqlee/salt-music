"""Send music to an Android phone with `adb push`, only what is missing."""

from __future__ import annotations

import re
import shlex
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable

from . import naming, proc, tools
from .library import AUDIO_EXT

# host:port; a host never starts with "-", or adb would read it as an option
ADDRESS_RE = re.compile(r"^(?:[A-Za-z0-9][A-Za-z0-9.-]*|\[[0-9A-Fa-f:.]+\]):\d{1,5}$")


@dataclass
class Device:
    serial: str
    state: str  # device | unauthorized | offline | no permissions
    model: str = ""


class AdbError(RuntimeError):
    pass


def available() -> bool:
    return tools.find(tools.ADB) is not None


_server_lock = threading.Lock()
_server_ok = False


def _exe() -> str:
    exe = tools.find(tools.ADB)
    if not exe:
        raise AdbError("adb_missing")
    return exe


def _ensure_server(exe: str) -> None:
    """Start the adb daemon with no pipes of ours.

    Any adb command starts the daemon when it is not running, and the daemon then
    inherits that command's stdout: reading the output would never reach the end.
    """
    global _server_ok
    with _server_lock:
        if _server_ok:
            return
        try:
            p = proc.spawn([exe, "start-server"])
            p.wait(timeout=20)
            _server_ok = p.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            pass


def _run(args: list[str], timeout: float = 30) -> str:
    exe = _exe()
    _ensure_server(exe)
    try:
        r = proc.run([exe, *args], timeout=timeout)
    except FileNotFoundError:
        raise AdbError("adb_missing")
    except subprocess.TimeoutExpired:
        raise AdbError("adb_timeout")
    if r.returncode != 0:
        raise AdbError((r.stderr or r.stdout).strip()[:500] or "adb error")
    return r.stdout


def devices() -> list[Device]:
    out = _run(["devices", "-l"], timeout=10)
    found = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 2:
            continue
        state = parts[1] if parts[1] != "no" else "no permissions"
        model = next((p.split(":", 1)[1] for p in parts if p.startswith("model:")), "")
        found.append(Device(parts[0], state, model.replace("_", " ")))
    return found


def _shell(serial: str, cmd: str, timeout: float = 60) -> str:
    return _run(["-s", serial, "shell", cmd], timeout=timeout)


def _listing(serial: str, root: str) -> tuple[set[str], dict[str, str]]:
    """key(rel file) of every remote file, and key(rel dir) -> real rel dir."""
    listing = _shell(serial, f"find {shlex.quote(root)} 2>/dev/null", timeout=120)
    files: set[str] = set()
    dirs: dict[str, str] = {}
    for line in listing.splitlines():
        line = line.strip()
        if not line.startswith(root + "/"):
            continue
        rel = line[len(root) + 1:]
        files.add(naming.key(rel))
        parent = str(PurePosixPath(rel).parent)
        while parent not in (".", ""):
            dirs.setdefault(naming.key(parent), parent)
            parent = str(PurePosixPath(parent).parent)
    return files, dirs


def _remote_rel(f: Path, base: Path, remote_dirs: dict[str, str]) -> tuple[list[str], str]:
    rel_parts = f.relative_to(base).parts
    # Map every directory to an existing remote one when possible.
    real: list[str] = []
    for part in rel_parts[:-1]:
        cand = "/".join([*real, part])
        real = remote_dirs.get(naming.key(cand), cand).split("/")
    return real, "/".join([*real, rel_parts[-1]])


def connect(address: str) -> str:
    """`adb connect host:port` for wireless debugging; returns adb's answer."""
    address = address.strip()
    if not ADDRESS_RE.match(address):
        raise AdbError("bad_address")
    out = _run(["connect", address], timeout=15).strip()
    if "cannot" in out or "failed" in out or "unable" in out:
        raise AdbError(out)
    return out


def info(serial: str, root: str) -> dict:
    """Android version, battery and free space where the music goes."""
    out: dict = {}
    try:
        out["android"] = _shell(serial, "getprop ro.build.version.release", timeout=10).strip()
    except AdbError:
        pass
    try:
        for line in _shell(serial, "dumpsys battery", timeout=10).splitlines():
            if line.strip().startswith("level:"):
                out["battery"] = int(line.split(":")[1])
    except (AdbError, ValueError):
        pass
    # df needs an existing path: walk up from the music folder
    path = root.rstrip("/") or "/"
    try:
        probe = f"p={shlex.quote(path)}; while [ ! -d \"$p\" ] && [ \"$p\" != / ]; do p=${{p%/*}}; [ -z \"$p\" ] && p=/; done; df -k \"$p\""
        lines = _shell(serial, probe, timeout=10).strip().splitlines()
        cols = lines[-1].split()
        out["total"], out["free"] = int(cols[1]) * 1024, int(cols[3]) * 1024
    except (AdbError, ValueError, IndexError):
        pass
    return out


def list_dirs(serial: str, path: str) -> tuple[str, list[str]]:
    """Folders inside `path` on the phone. A missing path falls back to its nearest existing parent,
    so the result is (the path really listed, sorted folder names)."""
    path = path.rstrip("/") or "/"
    script = (f"p={shlex.quote(path)}; while [ ! -d \"$p\" ] && [ \"$p\" != / ]; do p=${{p%/*}}; [ -z \"$p\" ] && p=/; done; "
              "cd \"$p\" && echo \"$p\" && for d in *; do [ -d \"$d\" ] && echo \"$d\"; done")
    lines = _shell(serial, script, timeout=15).splitlines()
    if not lines:
        raise AdbError("phone_dir_unreadable")
    return lines[0], sorted((l for l in lines[1:] if l), key=str.casefold)


def make_dir(serial: str, path: str) -> None:
    _shell(serial, f"mkdir -p {shlex.quote(path)}", timeout=15)


def compare(serial: str, base: Path, files: list[Path], remote_root: str) -> tuple[int, int, int]:
    """(files on the phone under the music folder, of `files` already there, of `files` missing)."""
    root = remote_root.rstrip("/")
    try:
        remote_files, remote_dirs = _listing(serial, root)
    except AdbError:
        remote_files, remote_dirs = set(), {}
    have = sum(1 for f in files if naming.key(_remote_rel(f, base, remote_dirs)[1]) in remote_files)
    on_phone = sum(1 for k in remote_files if PurePosixPath(k).suffix in AUDIO_EXT)
    return on_phone, have, len(files) - have


def push(
    serial: str,
    base: Path,
    files: list[Path],
    remote_root: str,
    progress: Callable[[int, int, Path, str], None],
    cancelled: Callable[[], bool] = lambda: False,
) -> tuple[int, int]:
    """Push `files` (inside `base`) to `remote_root`, keeping the folder layout.

    Existing remote folders are reused even if they differ in case; files that
    already exist are skipped. Returns (sent, skipped).
    """
    root = remote_root.rstrip("/")
    _shell(serial, f"mkdir -p {shlex.quote(root)}")
    remote_files, remote_dirs = _listing(serial, root)

    sent = skipped = 0
    made: set[str] = set()
    total = len(files)
    for i, f in enumerate(files, 1):
        if cancelled():
            break
        real, rel = _remote_rel(f, base, remote_dirs)
        if naming.key(rel) in remote_files:
            skipped += 1
            progress(i, total, f, "skipped")
            continue
        rdir = f"{root}/{'/'.join(real)}" if real else root
        if rdir not in made:
            _shell(serial, f"mkdir -p {shlex.quote(rdir)}")
            made.add(rdir)
            remote_dirs.setdefault(naming.key("/".join(real)), "/".join(real))
        progress(i, total, f, "sending")
        _run(["-s", serial, "push", str(f), f"{root}/{rel}"], timeout=600)
        remote_files.add(naming.key(rel))
        sent += 1
        progress(i, total, f, "sent")
    try:
        # Let the phone's media library see the new files.
        _shell(serial, f"am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d {shlex.quote('file://' + root)}")
    except AdbError:
        pass
    return sent, skipped
