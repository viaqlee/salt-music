"""Audio backend: a headless mpv process driven over its JSON IPC socket."""

from __future__ import annotations

import atexit
import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from typing import Callable


class AudioError(Exception):
    pass


def available() -> bool:
    return shutil.which("mpv") is not None


class Mpv:
    """on_event(name, value) is called from the reader thread:
    ("position", sec), ("duration", sec), ("paused", bool), ("ended", None)."""

    def __init__(self, on_event: Callable[[str, object], None]):
        self.on_event = on_event
        self._proc: subprocess.Popen | None = None
        self._sock: socket.socket | None = None
        self._lock = threading.Lock()
        self._last_pos = 0.0

    def _start(self) -> None:
        if self._proc and self._proc.poll() is None:
            return
        if not available():
            raise AudioError("mpv_missing")
        path = os.path.join(tempfile.gettempdir(), f"salt-music-mpv-{os.getpid()}.sock")
        if os.path.exists(path):
            os.unlink(path)
        self._proc = subprocess.Popen(
            ["mpv", "--idle=yes", "--no-video", "--no-terminal", "--audio-display=no",
             "--no-config", f"--input-ipc-server={path}"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        for _ in range(100):
            if os.path.exists(path):
                try:
                    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    s.connect(path)
                    self._sock = s
                    break
                except OSError:
                    pass
            time.sleep(0.05)
        else:
            raise AudioError("mpv_failed")
        atexit.register(self.stop)
        threading.Thread(target=self._reader, args=(s,), daemon=True).start()
        self._send("observe_property", 1, "time-pos")
        self._send("observe_property", 2, "duration")
        self._send("observe_property", 3, "pause")

    def _send(self, *command) -> None:
        data = (json.dumps({"command": list(command)}) + "\n").encode()
        with self._lock:
            try:
                self._sock.sendall(data)
            except (OSError, AttributeError):
                self._sock = None

    def _cmd(self, *command) -> None:
        self._start()
        self._send(*command)

    def _reader(self, sock: socket.socket) -> None:
        buf = b""
        while True:
            try:
                chunk = sock.recv(65536)
            except OSError:
                return
            if not chunk:
                return
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                self._dispatch(msg)

    def _dispatch(self, msg: dict) -> None:
        ev = msg.get("event")
        if ev == "property-change":
            name, data = msg.get("name"), msg.get("data")
            if name == "time-pos" and data is not None:
                # mpv reports many times a second; the UI needs ~4.
                if abs(data - self._last_pos) >= 0.25 or data < self._last_pos:
                    self._last_pos = data
                    self.on_event("position", float(data))
            elif name == "duration" and data is not None:
                self.on_event("duration", float(data))
            elif name == "pause" and data is not None:
                self.on_event("paused", bool(data))
        elif ev == "end-file" and msg.get("reason") == "eof":
            self.on_event("ended", None)

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
        if self._proc and self._proc.poll() is None:
            self._send("quit")
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None
