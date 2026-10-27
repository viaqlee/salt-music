"""Desktop integration behind one interface; the implementation is picked per platform.

    open_folder(path)    show a folder in the file manager
    notify(title, body)  system notification
    allow_foreground()   let the running copy raise its window (Windows)
    setup_process()      taskbar identity etc., called once at start-up
    claim()              single instance: InstanceServer, or None if another copy runs
"""

from __future__ import annotations

from pathlib import Path

from ..paths import IS_WINDOWS

if IS_WINDOWS:
    from . import _windows as _impl
else:
    from . import _linux as _impl

from .instance import InstanceServer, claim, wake_running  # noqa: E402

notify = _impl.notify
allow_foreground = _impl.allow_foreground
setup_process = _impl.setup_process


def open_folder(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    _impl.open_folder(folder)


__all__ = ["InstanceServer", "allow_foreground", "claim", "notify", "open_folder", "setup_process", "wake_running"]
