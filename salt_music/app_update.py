"""Updating Salt Music itself from GitHub releases.

check()    asks the GitHub API for the latest release and says whether it is newer.
download() fetches the installer for this system and checks it twice: against
           SHA256SUMS.txt from the same release and, when GitHub publishes one,
           against the asset's own sha256 digest. Only files of this repository's
           release are accepted, and sizes are capped.
launch()   starts the installer and leaves it to replace the program:
           Windows: the Inno Setup installer runs silently, closes the app and
                    starts the new version (see SaltMusic.iss, /RELAUNCH=1);
           Linux:   a small shell waits until this process is gone, runs the .run
                    installer unattended into the same folder and starts the app.

A portable copy or a run from sources can't be replaced this way: for those the
release page is opened instead.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import __version__, proc
from .paths import DATA_DIR, FROZEN, IS_WINDOWS, LOG_DIR, app_dir

log = logging.getLogger(__name__)

REPO = "viaqlee/salt-music"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
DOWNLOAD_PREFIX = f"https://github.com/{REPO}/releases/download/"
UPDATES_DIR = DATA_DIR / "updates"
SUMS = "SHA256SUMS.txt"
MAX_INSTALLER = 400 * 1024 * 1024
MAX_SMALL = 2 * 1024 * 1024
UA = {"User-Agent": "SaltMusic-updater", "Accept": "application/vnd.github+json"}


class UpdateError(RuntimeError):
    pass


@dataclass
class Asset:
    name: str
    url: str
    size: int
    digest: str = ""  # sha256 hex published by GitHub, if any


@dataclass
class Release:
    version: str
    tag: str
    page: str
    notes: str
    assets: dict[str, Asset] = field(default_factory=dict)


# ---------- versions ----------

def parse_version(text: str) -> tuple[int, ...] | None:
    m = re.fullmatch(r"v?(\d{1,6}(?:\.\d{1,6}){0,3})", text.strip())
    return tuple(int(x) for x in m.group(1).split(".")) if m else None


def is_newer(remote: str, local: str) -> bool:
    r, loc = parse_version(remote), parse_version(local)
    if r is None or loc is None:
        return False
    width = max(len(r), len(loc))
    return r + (0,) * (width - len(r)) > loc + (0,) * (width - len(loc))


# ---------- how this copy was installed ----------

def install_kind() -> str | None:
    """"windows" (Inno Setup install), "linux" (.run install) or None (portable / sources)."""
    here = app_dir()
    if IS_WINDOWS:
        return "windows" if FROZEN and (here / "unins000.exe").is_file() else None
    if (here / ".version").is_file() and (here / "uninstall.run").is_file() and (here / ".venv").is_dir():
        return "linux"
    return None


def asset_name(version: str, kind: str) -> str:
    return f"SaltMusic-Setup-{version}.exe" if kind == "windows" else f"SaltMusic-Setup-{version}.run"


# ---------- network ----------

def _open(url: str, timeout: float = 30):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout)


def _get(url: str, limit: int) -> bytes:
    with _open(url) as r:
        data = r.read(limit + 1)
    if len(data) > limit:
        raise UpdateError(f"{url}: too large")
    return data


def _parse_release(meta: dict) -> Release:
    tag = str(meta.get("tag_name") or "")
    version = tag.removeprefix("v")
    if parse_version(version) is None:
        raise UpdateError(f"odd release tag: {tag!r}")
    assets = {}
    for a in meta.get("assets") or []:
        name, url = str(a.get("name") or ""), str(a.get("browser_download_url") or "")
        # only files of this very release; anything else is ignored
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,120}", name) or url != f"{DOWNLOAD_PREFIX}{tag}/{name}":
            continue
        digest = str(a.get("digest") or "")
        digest = digest.removeprefix("sha256:") if re.fullmatch(r"sha256:[0-9a-f]{64}", digest) else ""
        size = a.get("size")
        assets[name] = Asset(name, url, size if isinstance(size, int) and size > 0 else 0, digest)
    page = str(meta.get("html_url") or "")
    if not page.startswith(f"https://github.com/{REPO}/releases/"):
        page = f"https://github.com/{REPO}/releases/latest"
    return Release(version, tag, page, str(meta.get("body") or "")[:4000], assets)


def check(current: str = __version__, fetch=_get) -> Release | None:
    """The latest release when it is newer than `current`, else None."""
    try:
        meta = json.loads(fetch(API, MAX_SMALL))
    except ValueError as err:
        raise UpdateError("bad answer from GitHub") from err
    if not isinstance(meta, dict) or meta.get("draft") or meta.get("prerelease"):
        return None
    release = _parse_release(meta)
    return release if is_newer(release.version, current) else None


def _sums(release: Release, fetch=_get) -> dict[str, str]:
    asset = release.assets.get(SUMS)
    if not asset:
        raise UpdateError(f"{SUMS} is missing from the release")
    out = {}
    for line in fetch(asset.url, 64 * 1024).decode("utf-8", "replace").splitlines():
        m = re.fullmatch(r"([0-9a-fA-F]{64})\s+\*?([A-Za-z0-9._-]{1,120})", line.strip())
        if m:
            out[m.group(2)] = m.group(1).lower()
    return out


def _stream(url: str, target: Path, limit: int, progress: Callable[[float], None] | None) -> str:
    """Download to `target`, returning the sha256 of what was written."""
    h = hashlib.sha256()
    done = 0
    with _open(url, timeout=60) as r, open(target, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        if total > limit:
            raise UpdateError(f"{url}: too large")
        while chunk := r.read(256 * 1024):
            done += len(chunk)
            if done > limit:
                raise UpdateError(f"{url}: too large")
            h.update(chunk)
            f.write(chunk)
            if progress and total:
                progress(done / total)
    return h.hexdigest()


def download(release: Release, kind: str, folder: Path = UPDATES_DIR, fetch=_get, stream=_stream,
             progress: Callable[[float], None] | None = None) -> Path:
    """Fetch and verify the installer of `release` for `kind`. Returns its path."""
    name = asset_name(release.version, kind)
    asset = release.assets.get(name)
    if not asset:
        raise UpdateError(f"{name} is missing from the release")
    expected = _sums(release, fetch).get(name)
    if not expected:
        raise UpdateError(f"{name} is not listed in {SUMS}")
    if asset.digest and asset.digest != expected:
        raise UpdateError(f"{name}: checksums of the release disagree")
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True, exist_ok=True)
    part = folder / (name + ".part")
    limit = min(asset.size, MAX_INSTALLER) if asset.size else MAX_INSTALLER
    try:
        got = stream(asset.url, part, limit, progress)
        if got != expected:
            raise UpdateError(f"{name}: checksum mismatch")
        final = folder / name
        part.replace(final)
    finally:
        part.unlink(missing_ok=True)
    if kind == "linux":
        final.chmod(0o700)
    log.info("downloaded %s (%s)", name, expected)
    return final


def cleanup(folder: Path = UPDATES_DIR) -> None:
    """Remove installers left from an update that is already done."""
    shutil.rmtree(folder, ignore_errors=True)


# ---------- install ----------

# waits for the app to exit, installs over it and starts the new version;
# arguments come as $1..$4, never pasted into the script text
_LINUX_SCRIPT = """
while kill -0 "$1" 2>/dev/null; do sleep 0.3; done
bash "$2" --unattended --prefix "$3" > "$4" 2>&1 && exec "$3/salt-music"
"""


def launch(installer: Path, kind: str) -> None:
    """Start the installer. The caller quits right after this."""
    if kind == "windows":
        # /RELAUNCH=1 makes the silent setup start the app again when it is done
        p = proc.spawn([str(installer), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS",
                        "/MERGETASKS=!tools", "/RELAUNCH=1"])
    elif kind == "linux":
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        p = proc.spawn(["/bin/sh", "-c", _LINUX_SCRIPT, "salt-update", str(os.getpid()), str(installer),
                        str(app_dir()), str(LOG_DIR / "update.log")])
    else:
        raise UpdateError(f"can't install over a {kind} copy")
    log.info("update started: %s (pid %s)", installer.name, p.pid)
