"""Updating yt-dlp without pip.

The packed .exe has no pip and its own files may be read-only (Program Files),
so new versions of the pure-Python packages yt-dlp and yt-dlp-ejs are unpacked
into %LOCALAPPDATA%\\SaltMusic\\packages\\<version> and put first on sys.path
at the next start. Every wheel is checked against the SHA-256 published by PyPI.

Folders are versioned and the running one is never touched: yt-dlp imports its
extractors lazily, so swapping files under a running app would mix versions.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import re
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

from .paths import PACKAGES_DIR

log = logging.getLogger(__name__)

PACKAGES = ("yt-dlp", "yt-dlp-ejs")
PYPI = "https://pypi.org/pypi/{name}/json"
ALLOWED_HOSTS = ("https://files.pythonhosted.org/",)
MAX_WHEEL = 40 * 1024 * 1024
POINTER = "current.txt"
UA = {"User-Agent": "SaltMusic-updater"}


class UpdateError(RuntimeError):
    pass


# ---------- start-up ----------

def activate(root: Path = PACKAGES_DIR) -> str | None:
    """Put the installed update first on sys.path. Call before anything imports yt_dlp.

    Returns the version that was activated. Old version folders are removed here,
    while nothing uses them.
    """
    try:
        name = (root / POINTER).read_text("utf-8").strip()
    except OSError:
        return None
    current = root / name
    if not _valid_name(name) or not (current / "yt_dlp").is_dir():
        return None
    for old in root.iterdir():
        if old.is_dir() and old.name != current.name:
            shutil.rmtree(old, ignore_errors=True)
    if str(current) not in sys.path:
        sys.path.insert(0, str(current))
    return name


def active_version(root: Path = PACKAGES_DIR) -> str | None:
    try:
        name = (root / POINTER).read_text("utf-8").strip()
    except OSError:
        return None
    return name if _valid_name(name) else None


def reset(root: Path = PACKAGES_DIR) -> None:
    """Go back to the yt-dlp built into the program (after the next start)."""
    (root / POINTER).unlink(missing_ok=True)


def _valid_name(name: str) -> bool:
    return bool(re.fullmatch(r"[0-9][0-9A-Za-z.+_-]{0,60}", name))


# ---------- download ----------

def _get(url: str, limit: int, timeout: float = 30) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read(limit + 1)
    if len(data) > limit:
        raise UpdateError(f"{url}: too large")
    return data


def _requires_ok(spec: str | None) -> bool:
    """Very small check of `requires_python` (">=3.10" and the like)."""
    if not spec:
        return True
    have = sys.version_info[:2]
    for part in spec.split(","):
        m = re.fullmatch(r"\s*(>=|>|<=|<|==|!=)\s*(\d+)\.(\d+)(?:\.\d+)?(?:\.\*)?\s*", part)
        if not m:
            continue
        op, want = m.group(1), (int(m.group(2)), int(m.group(3)))
        ok = {">=": have >= want, ">": have > want, "<=": have <= want, "<": have < want,
              "==": have == want, "!=": have != want}[op]
        if not ok:
            return False
    return True


def latest(name: str, fetch=_get) -> tuple[str, str, str]:
    """(version, wheel url, sha256) of the newest pure-Python wheel on PyPI."""
    meta = json.loads(fetch(PYPI.format(name=name), 5 * 1024 * 1024))
    version = meta["info"]["version"]
    if not _requires_ok(meta["info"].get("requires_python")):
        raise UpdateError(f"{name} {version} needs Python {meta['info']['requires_python']}")
    for f in meta.get("urls", []):
        if f.get("packagetype") == "bdist_wheel" and f.get("filename", "").endswith("-py3-none-any.whl"):
            url, sha = f.get("url", ""), (f.get("digests") or {}).get("sha256", "")
            if not url.startswith(ALLOWED_HOSTS) or not re.fullmatch(r"[0-9a-f]{64}", sha):
                raise UpdateError(f"{name}: unexpected download location")
            return version, url, sha
    raise UpdateError(f"{name} {version}: no wheel")


def _extract(wheel: bytes, target: Path) -> None:
    """Unpack a wheel, refusing anything that would land outside `target`."""
    with zipfile.ZipFile(io.BytesIO(wheel)) as zf:
        for info in zf.infolist():
            p = PurePosixPath(info.filename)
            if p.is_absolute() or ".." in p.parts or ":" in info.filename or "\\" in info.filename:
                raise UpdateError(f"bad path in wheel: {info.filename}")
        zf.extractall(target)


def update(current: str | None = None, root: Path = PACKAGES_DIR, fetch=_get) -> str | None:
    """Install the newest yt-dlp (+ yt-dlp-ejs) for the next start.

    Returns the new version, or None when `current` already is the newest.
    """
    found = [(name, *latest(name, fetch)) for name in PACKAGES]
    version = found[0][1]
    if version == current:
        return None
    if not _valid_name(version):
        raise UpdateError(f"odd version: {version}")
    root.mkdir(parents=True, exist_ok=True)
    staging = root / f".staging-{version}"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir()
    try:
        for name, ver, url, sha in found:
            data = fetch(url, MAX_WHEEL)
            if hashlib.sha256(data).hexdigest() != sha:
                raise UpdateError(f"{name} {ver}: checksum mismatch")
            _extract(data, staging)
            log.info("downloaded %s %s", name, ver)
        if not (staging / "yt_dlp" / "__init__.py").is_file():
            raise UpdateError("yt_dlp missing from the wheel")
        final = root / version
        if final.exists() and active_version(root) != version:
            shutil.rmtree(final)
        if not final.exists():
            staging.rename(final)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    tmp = root / (POINTER + ".tmp")
    tmp.write_text(version, "utf-8")
    tmp.replace(root / POINTER)
    return version
