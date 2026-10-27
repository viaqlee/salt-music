"""One running copy per profile.

The first copy takes a lock (a named mutex on Windows, flock on Linux) and
listens on a local channel (named pipe / unix socket). A later launch finds the
lock taken, asks the running copy to show its window and exits.

The channel is authenticated with a random key from the profile folder, so other
users and programs on the machine cannot talk to it, and it only ever exchanges
raw bytes: the multiprocessing pickling layer is never used.
"""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
import tempfile
import threading
import time
from multiprocessing.connection import Client, Listener
from pathlib import Path
from typing import Callable

from ..paths import DATA_DIR, IS_WINDOWS

log = logging.getLogger(__name__)

MESSAGE = b"show"


def _tag(data_dir: Path) -> str:
    # one running copy per profile (data folder), not per user
    return hashlib.sha1(str(data_dir).encode("utf-8")).hexdigest()[:10]


def _user() -> str:
    if IS_WINDOWS:
        return hashlib.sha1((os.environ.get("USERNAME", "") + os.environ.get("USERDOMAIN", "")).encode()).hexdigest()[:8]
    return str(os.getuid())


def address(data_dir: Path = DATA_DIR) -> tuple[str, str]:
    """(address, multiprocessing family) of the wake-up channel."""
    name = f"salt-music-{_user()}-{_tag(data_dir)}"
    if IS_WINDOWS:
        return rf"\\.\pipe\{name}", "AF_PIPE"
    run = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
    return os.path.join(run, name + ".sock"), "AF_UNIX"


def _key(data_dir: Path) -> bytes:
    path = data_dir / "instance.key"
    try:
        key = path.read_bytes()
        if len(key) >= 32:
            return key
    except OSError:
        pass
    data_dir.mkdir(parents=True, exist_ok=True)
    key = secrets.token_bytes(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0), 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(key)
    return key


class _Lock:
    """Held for the whole life of the process; the OS frees it when we exit or crash."""

    def __init__(self, data_dir: Path):
        self._handle = None
        self._file = None
        self.data_dir = data_dir

    def acquire(self) -> bool:
        if IS_WINDOWS:
            import ctypes
            from ctypes import wintypes

            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.CreateMutexW.restype = wintypes.HANDLE
            k32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
            handle = k32.CreateMutexW(None, False, f"Local\\salt-music-{_tag(self.data_dir)}")
            if not handle:
                return True  # cannot tell: better two copies than none
            if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
                k32.CloseHandle(handle)
                return False
            self._handle = handle
            return True
        import fcntl

        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._file = open(self.data_dir / "instance.lock", "a+")
        try:
            fcntl.flock(self._file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self._file.close()
            self._file = None
            return False
        return True


def wake_running(data_dir: Path = DATA_DIR, attempts: int = 1) -> bool:
    """Ask the running copy to show its window. True if it answered."""
    addr, family = address(data_dir)
    key = _key(data_dir)
    for i in range(attempts):
        try:
            with Client(addr, family=family, authkey=key) as c:
                c.send_bytes(MESSAGE)
            return True
        except (OSError, EOFError, ConnectionError) as e:
            log.debug("wake failed: %s", e)
        except Exception as e:  # multiprocessing.AuthenticationError and friends
            log.warning("wake rejected: %s", e)
            return False
        if i + 1 < attempts:
            time.sleep(0.3)
    return False


class InstanceServer:
    """Listens for wake_running() of later launches; on_show runs on a background thread."""

    def __init__(self, data_dir: Path = DATA_DIR):
        self.on_show: Callable[[], None] | None = None
        addr, family = address(data_dir)
        if family == "AF_UNIX":
            try:
                os.unlink(addr)  # left over from a crash: we hold the lock, nobody listens there
            except OSError:
                pass
        self._listener = Listener(addr, family=family, authkey=_key(data_dir))
        threading.Thread(target=self._serve, daemon=True, name="salt-instance").start()

    def _serve(self) -> None:
        while True:
            try:
                conn = self._listener.accept()
            except OSError:
                return
            except Exception as e:  # failed authentication: ignore that caller
                log.warning("rejected a wake-up: %s", e)
                continue
            with conn:
                try:
                    msg = conn.recv_bytes(maxlength=64)
                except (OSError, EOFError):
                    continue
            if msg == MESSAGE and self.on_show:
                try:
                    self.on_show()
                except Exception:
                    log.exception("on_show failed")

    def close(self) -> None:
        try:
            self._listener.close()
        except OSError:
            pass


def claim(data_dir: Path = DATA_DIR) -> InstanceServer | None:
    """Become the running copy, or wake the existing one and return None."""
    lock = _Lock(data_dir)
    if lock.acquire():
        server = InstanceServer(data_dir)
        server._lock = lock  # type: ignore[attr-defined]  # keep it alive with the server
        return server
    from . import allow_foreground

    allow_foreground()
    # the other copy may still be starting up and not listening yet
    wake_running(data_dir, attempts=10)
    return None
