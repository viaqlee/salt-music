"""Linux desktop: xdg-open, notify-send, and raising the file manager on KDE Wayland."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from .. import proc

_SCRIPT = "salt-music-raise"


def _default_file_manager() -> str:
    """Desktop id of the default file manager, e.g. "org.kde.dolphin"."""
    try:
        out = proc.run(["xdg-mime", "query", "default", "inode/directory"], timeout=5).stdout.strip()
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
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(js)
    try:
        def call(*args):
            return proc.run([qdbus, "org.kde.KWin", *args], timeout=5).stdout.strip()

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
    if not shutil.which("xdg-open"):
        raise FileNotFoundError("xdg-open")
    proc.spawn(["xdg-open", str(folder)])
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
        proc.spawn(["notify-send", "-a", "Salt Music", "-i", "folder-music", title, body])


def allow_foreground() -> None:
    """Nothing to do: the running copy raises itself."""


def setup_process() -> None:
    """Nothing to do on Linux."""
