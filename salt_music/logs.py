"""Logging to a rotating file. A packed Windows app has no console, so this is the only trace."""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from .paths import LOG_DIR

log = logging.getLogger("salt_music")


def setup(level: int = logging.INFO) -> None:
    # A windowed .exe starts with sys.stdout / sys.stderr = None: any print() or
    # traceback would raise inside the thread that made it.
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
    root = logging.getLogger()
    if any(getattr(h, "_salt", False) for h in root.handlers):
        return
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s [%(threadName)s] %(message)s")
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        handler: logging.Handler = RotatingFileHandler(LOG_DIR / "salt-music.log", maxBytes=1_000_000,
                                                       backupCount=3, encoding="utf-8", delay=True)
    except OSError:
        handler = logging.StreamHandler()
    handler._salt = True  # type: ignore[attr-defined]
    handler.setFormatter(fmt)
    root.addHandler(handler)
    root.setLevel(level)
    # flet is chatty on INFO
    logging.getLogger("flet").setLevel(logging.WARNING)
    logging.getLogger("flet_desktop").setLevel(logging.WARNING)


class YtdlpLogger:
    """yt-dlp writes to stderr unless given a logger; route it into our log instead."""

    def __init__(self) -> None:
        self._log = logging.getLogger("salt_music.yt_dlp")

    def debug(self, msg: str) -> None:
        if not msg.startswith("[debug] "):
            self._log.debug(msg)

    def info(self, msg: str) -> None:
        self._log.debug(msg)

    def warning(self, msg: str) -> None:
        self._log.warning(msg)

    def error(self, msg: str) -> None:
        self._log.error(msg)
