"""Windows desktop: Explorer, toast notifications, taskbar identity, foreground rights."""

from __future__ import annotations

import base64
import logging
import os
import sys
from pathlib import Path

from .. import AUMID, proc

log = logging.getLogger(__name__)

# Toasts need an AppUserModelID with a Start-menu shortcut behind it. The installer
# creates ours; a copy started from sources borrows the one of PowerShell.
_POWERSHELL_AUMID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"

# Title and text come in through environment variables, never through the script
# text itself, so no file name or track title can turn into PowerShell code.
_TOAST = r"""
$ErrorActionPreference = 'Stop'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
$x = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$t = $x.GetElementsByTagName('text')
$t.Item(0).AppendChild($x.CreateTextNode($env:SALT_TOAST_TITLE)) > $null
$t.Item(1).AppendChild($x.CreateTextNode($env:SALT_TOAST_BODY)) > $null
$n = [Windows.UI.Notifications.ToastNotification]::new($x)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($env:SALT_TOAST_APP).Show($n)
"""


def _powershell() -> str:
    root = os.environ.get("SystemRoot") or r"C:\Windows"
    return str(Path(root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe")


def _installed() -> bool:
    """Packed and installed: our shortcut (and so our AUMID) exists."""
    return bool(getattr(sys, "frozen", False))


def open_folder(folder: Path) -> None:
    os.startfile(str(folder))  # type: ignore[attr-defined]  # Explorer comes to the front by itself


def notify(title: str, body: str) -> None:
    env = {
        **os.environ,
        "SALT_TOAST_TITLE": title[:200],
        "SALT_TOAST_BODY": body[:500],
        "SALT_TOAST_APP": AUMID if _installed() else _POWERSHELL_AUMID,
    }
    script = base64.b64encode(_TOAST.encode("utf-16-le")).decode("ascii")
    try:
        proc.spawn([_powershell(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                    "-EncodedCommand", script], env=env)
    except OSError as e:
        log.warning("toast failed: %s", e)


def allow_foreground() -> None:
    """Let the already running copy take the foreground when this one wakes it.

    Windows only lets the process that got the user's input (this one, just
    started from the Start menu) bring a window to the front.
    """
    try:
        import ctypes

        ctypes.windll.user32.AllowSetForegroundWindow(-1)  # ASFW_ANY
    except (OSError, AttributeError):
        pass


def setup_process() -> None:
    """Taskbar grouping and toasts under our own name and icon."""
    os.environ.setdefault("FLET_APP_USER_MODEL_ID", AUMID)
    if _installed():
        exe = os.path.abspath(sys.executable)
        # the flet PyInstaller hook already set these to the exe; keep ours consistent
        os.environ["FLET_APP_USER_MODEL_ID"] = AUMID
        os.environ.setdefault("FLET_APP_RELAUNCH_COMMAND", f'"{exe}"')
        os.environ.setdefault("FLET_APP_RELAUNCH_DISPLAY_NAME", "Salt Music")
        os.environ.setdefault("FLET_APP_RELAUNCH_ICON", f"{exe},0")
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(os.environ["FLET_APP_USER_MODEL_ID"])
    except (OSError, AttributeError):
        pass
