"""Audio backend: a headless mpv process driven over its JSON IPC.

The IPC channel is a unix socket on Linux and a named pipe on Windows. mpv's IPC
can run arbitrary commands, so the socket lives in a private 0700 folder; a
Windows pipe only admits the same user by default.
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import queue
import secrets
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from typing import Callable

from . import proc, tools
from .paths import IS_WINDOWS

log = logging.getLogger(__name__)


class AudioError(Exception):
    pass


def available() -> bool:
    return tools.find(tools.MPV) is not None


# ---------- transports: deliver bytes both ways, report the end once ----------

class _SocketTransport:
    def __init__(self, path: str):
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.connect(path)
        self._lock = threading.Lock()

    def start(self, on_data: Callable[[bytes], None]) -> None:
        threading.Thread(target=self._read, args=(on_data,), daemon=True, name="salt-mpv").start()

    def _read(self, on_data) -> None:
        while True:
            try:
                chunk = self._sock.recv(65536)
            except OSError:
                return
            if not chunk:
                return
            on_data(chunk)

    def send(self, data: bytes) -> bool:
        with self._lock:
            try:
                self._sock.sendall(data)
                return True
            except OSError:
                return False

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass


class _PipeTransport:
    """mpv's named pipe, opened for synchronous IO.

    Windows serializes all IO on a synchronous handle: a ReadFile waiting for data
    would block every WriteFile from another thread. So one thread does both,
    reading only what PeekNamedPipe says is there and writing from a queue.
    """

    POLL = 0.02

    def __init__(self, name: str):
        import _winapi

        self._w = _winapi
        self._handle = _winapi.CreateFile(name, _winapi.GENERIC_READ | _winapi.GENERIC_WRITE,
                                          0, _winapi.NULL, _winapi.OPEN_EXISTING, 0, _winapi.NULL)
        self._out: queue.SimpleQueue[bytes | None] = queue.SimpleQueue()
        self._closed = threading.Event()

    def start(self, on_data: Callable[[bytes], None]) -> None:
        threading.Thread(target=self._loop, args=(on_data,), daemon=True, name="salt-mpv").start()

    def _loop(self, on_data) -> None:
        w = self._w
        try:
            while not self._closed.is_set():
                busy = False
                while True:
                    try:
                        data = self._out.get_nowait()
                    except queue.Empty:
                        break
                    if data is None:
                        return
                    w.WriteFile(self._handle, data)
                    busy = True
                avail, _ = w.PeekNamedPipe(self._handle)
                if avail:
                    chunk, _ = w.ReadFile(self._handle, avail)
                    on_data(chunk)
                    busy = True
                if not busy:
                    time.sleep(self.POLL)
        except OSError:
            pass  # mpv quit: the pipe is broken
        finally:
            self._closed.set()
            try:
                w.CloseHandle(self._handle)
            except OSError:
                pass

    def send(self, data: bytes) -> bool:
        if self._closed.is_set():
            return False
        self._out.put(data)
        return True

    def close(self) -> None:
        if not self._closed.is_set():
            self._out.put(None)


def _ipc_address() -> tuple[str, Callable[[], None]]:
    """(address for --input-ipc-server, cleanup)."""
    tag = f"salt-music-mpv-{os.getpid()}-{secrets.token_hex(4)}"
    if IS_WINDOWS:
        return rf"\\.\pipe\{tag}", lambda: None
    folder = tempfile.mkdtemp(prefix="salt-music-")  # 0700
    return os.path.join(folder, "mpv.sock"), lambda: shutil.rmtree(folder, ignore_errors=True)


def _connect(addr: str):
    if IS_WINDOWS:
        return _PipeTransport(addr)
    if not os.path.exists(addr):
        raise FileNotFoundError(addr)
    return _SocketTransport(addr)


class Mpv:
    """on_event(name, value) is called from the reader thread:
    ("position", sec), ("duration", sec), ("paused", bool), ("ended", None)."""

    def __init__(self, on_event: Callable[[str, object], None]):
        self.on_event = on_event
        self._proc: subprocess.Popen | None = None
        self._io = None
        self._cleanup: Callable[[], None] = lambda: None
        self._start_lock = threading.Lock()
        self._last_pos = 0.0
        self._buf = b""
        atexit.register(self.stop)

    def _start(self) -> None:
        with self._start_lock:
            if self._proc and self._proc.poll() is None and self._io:
                return
            self._shutdown()
            exe = tools.find(tools.MPV)
            if not exe:
                raise AudioError("mpv_missing")
            addr, self._cleanup = _ipc_address()
            try:
                self._proc = proc.spawn(
                    [exe, "--idle=yes", "--no-video", "--no-terminal", "--audio-display=no",
                     "--no-config", "--really-quiet", f"--input-ipc-server={addr}"])
            except OSError as e:
                log.warning("mpv did not start: %s", e)
                raise AudioError("mpv_failed") from e
            proc.tie_to_app(self._proc)
            for _ in range(100):
                if self._proc.poll() is not None:
                    break
                try:
                    self._io = _connect(addr)
                    break
                except OSError:
                    time.sleep(0.05)
            if not self._io:
                self._shutdown()
                raise AudioError("mpv_failed")
            self._buf = b""
            self._io.start(self._on_data)
            self._send("observe_property", 1, "time-pos")
            self._send("observe_property", 2, "duration")
            self._send("observe_property", 3, "pause")

    def _send(self, *command) -> None:
        io = self._io
        if io and not io.send((json.dumps({"command": list(command)}) + "\n").encode("utf-8")):
            self._io = None

    def _cmd(self, *command) -> None:
        self._start()
        self._send(*command)

    def _on_data(self, chunk: bytes) -> None:
        self._buf += chunk
        if len(self._buf) > 1 << 20:  # no line from mpv is that long: drop garbage
            self._buf = b""
        while b"\n" in self._buf:
            line, self._buf = self._buf.split(b"\n", 1)
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if isinstance(msg, dict):
                try:
                    self._dispatch(msg)
                except Exception:
                    log.exception("mpv event handler failed")

    def _dispatch(self, msg: dict) -> None:
        ev = msg.get("event")
        if ev == "property-change":
            name, data = msg.get("name"), msg.get("data")
            if name == "time-pos" and isinstance(data, (int, float)):
                # mpv reports many times a second; the UI needs ~4.
                if abs(data - self._last_pos) >= 0.25 or data < self._last_pos:
                    self._last_pos = data
                    self.on_event("position", float(data))
            elif name == "duration" and isinstance(data, (int, float)):
                self.on_event("duration", float(data))
            elif name == "pause" and data is not None:
                self.on_event("paused", bool(data))
        elif ev == "end-file" and msg.get("reason") == "eof":
            self.on_event("ended", None)

    def _shutdown(self) -> None:
        if self._io:
            self._io.close()
            self._io = None
        if self._proc and self._proc.poll() is None:
            self._proc.kill()
        self._proc = None
        self._cleanup()
        self._cleanup = lambda: None

    # ---------- public ----------

    def load(self, path: str) -> None:
        self._last_pos = 0.0
        self._cmd("loadfile", path, "replace")
        self._send("set_property", "pause", False)

    def set_paused(self, paused: bool) -> None:
        self._cmd("set_property", "pause", paused)

    def seek(self, seconds: float) -> None:
        self._cmd("seek", max(0.0, seconds), "absolute")

    def set_volume(self, volume: float) -> None:
        self._cmd("set_property", "volume", round(volume * 100))

    def stop(self) -> None:
        p = self._proc
        if p and p.poll() is None:
            self._send("quit")
            try:
                p.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
        self._shutdown()
