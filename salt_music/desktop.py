"""Opening folders in the user's default file manager."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from pathlib import Path

_SCRIPT = "salt-music-raise"


def _default_file_manager() -> str:
    """Desktop id of the default file manager, e.g. "org.kde.dolphin"."""
    try:
        out = subprocess.run(["xdg-mime", "query", "default", "inode/directory"],
                             capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return out.removesuffix(".desktop")


def _kwin_raise(folder: Path, app_id: str) -> None:
    """KWin on Wayland keeps windows opened by another app in the background
    (focus stealing prevention), so ask it directly to bring the window forward."""
    qdbus = shutil.which("qdbus6") or shutil.which("qdbus")
    if not qdbus:
        return
    short = app_id.rsplit(".", 1)[-1].lower()
    js = f"""
const name = {json.dumps(folder.name)}, appId = {json.dumps(app_id)}, short = {json.dumps(short)};
const fm = workspace.windowList().filter(w => w.normalWindow &&
    (w.desktopFileName === appId || String(w.resourceClass).toLowerCase().includes(short)));
const hit = fm.filter(w => w.caption.includes(name));
const w = (hit.length ? hit : fm)[(hit.length ? hit : fm).length - 1];
if (w) {{ if (w.minimized) w.minimized = false; workspace.activeWindow = w; }}
"""
    fd, path = tempfile.mkstemp(prefix="salt-raise-", suffix=".js")
    with os.fdopen(fd, "w") as f:
        f.write(js)
    try:
        def call(*args):
            return subprocess.run([qdbus, "org.kde.KWin", *args], capture_output=True, text=True,
                                  timeout=5).stdout.strip()

        call("/Scripting", "org.kde.kwin.Scripting.unloadScript", _SCRIPT)
        sid = call("/Scripting", "org.kde.kwin.Scripting.loadScript", path, _SCRIPT)
        if sid.lstrip("-").isdigit() and int(sid) >= 0:
            call(f"/Scripting/Script{sid}", "org.kde.kwin.Script.run")
            time.sleep(0.3)
        call("/Scripting", "org.kde.kwin.Scripting.unloadScript", _SCRIPT)
    except (OSError, subprocess.TimeoutExpired):
        pass
    finally:
        os.unlink(path)


def open_folder(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    if not shutil.which("xdg-open"):
        raise FileNotFoundError("xdg-open")
    subprocess.Popen(["xdg-open", str(folder)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)
    if "KDE" not in os.environ.get("XDG_CURRENT_DESKTOP", "").upper():
        return

    def raise_later():
        app_id = _default_file_manager()
        # the window shows up after a moment; a second pass covers slow starts
        for delay in (0.8, 1.2):
            time.sleep(delay)
            _kwin_raise(folder, app_id)

    threading.Thread(target=raise_later, daemon=True).start()


def notify(title: str, body: str) -> None:
    if shutil.which("notify-send"):
        subprocess.Popen(["notify-send", "-a", "Salt Music", "-i", "folder-music", title, body],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def _socket_path() -> str:
    from .config import DATA_DIR

    run = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
    # one running copy per profile (data folder), not per user
    tag = hashlib.sha1(str(DATA_DIR).encode()).hexdigest()[:8]
    return os.path.join(run, f"salt-music-{os.getuid()}-{tag}.sock")


def wake_running() -> bool:
    """A copy already runs (maybe hidden, downloading): ask it to show up instead of starting again."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as c:
            c.settimeout(2)
            c.connect(_socket_path())
            c.sendall(b"show\n")
        return True
    except OSError:
        return False


class InstanceServer:
    """Listens for wake_running() of later launches."""

    def __init__(self):
        self.on_show = None
        path = _socket_path()
        try:
            os.unlink(path)  # left over from a crash: wake_running() already found nobody there
        except OSError:
            pass
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.bind(path)
        self._sock.listen(4)
        threading.Thread(target=self._serve, daemon=True, name="salt-instance").start()

    def _serve(self) -> None:
        while True:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return
            with conn:
                try:
                    msg = conn.recv(64)
                except OSError:
                    continue
            if msg.startswith(b"show") and self.on_show:
                self.on_show()
