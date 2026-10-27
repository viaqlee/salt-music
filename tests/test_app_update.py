"""Self-update from GitHub releases: version checks, verification, refusals."""

import hashlib
import json
import sys

import pytest

from salt_music import app_update
from salt_music.app_update import DOWNLOAD_PREFIX, UpdateError

INSTALLER = b"pretend installer" * 1000


def _release(version="9.0.0", payload=INSTALLER, sums_hash=None, digest=None, url=None, extra=None):
    tag = f"v{version}"
    name = f"SaltMusic-Setup-{version}.exe"
    sha = hashlib.sha256(payload).hexdigest()
    sums = f"{sums_hash or sha}  {name}\n{'0' * 64}  SaltMusic-Setup-{version}.run\n".encode()
    assets = [
        {"name": name, "browser_download_url": url or f"{DOWNLOAD_PREFIX}{tag}/{name}", "size": len(payload),
         **({"digest": digest} if digest else {})},
        {"name": "SHA256SUMS.txt", "browser_download_url": f"{DOWNLOAD_PREFIX}{tag}/SHA256SUMS.txt", "size": len(sums)},
        *(extra or []),
    ]
    meta = {"tag_name": tag, "html_url": f"https://github.com/viaqlee/salt-music/releases/tag/{tag}",
            "body": "notes", "assets": assets}
    files = {app_update.API: json.dumps(meta).encode(), f"{DOWNLOAD_PREFIX}{tag}/SHA256SUMS.txt": sums}

    def fetch(u, limit):
        return files[u]

    def stream(u, target, limit, progress):
        assert u.startswith(f"{DOWNLOAD_PREFIX}{tag}/")
        target.write_bytes(payload)
        return hashlib.sha256(payload).hexdigest()

    return fetch, stream


def test_versions():
    assert app_update.is_newer("0.3.0", "0.2.1")
    assert app_update.is_newer("v1.0", "0.9.9")
    assert app_update.is_newer("0.2.10", "0.2.9")
    assert not app_update.is_newer("0.2.1", "0.2.1")
    assert not app_update.is_newer("0.2", "0.2.0")
    assert not app_update.is_newer("0.1.9", "0.2.0")
    assert not app_update.is_newer("latest", "0.2.0")
    assert not app_update.is_newer("1.0-rc1", "0.2.0")


def test_check_newer_and_same():
    fetch, _ = _release("9.0.0")
    r = app_update.check("0.2.1", fetch=fetch)
    assert r and r.version == "9.0.0" and r.tag == "v9.0.0"
    assert "SaltMusic-Setup-9.0.0.exe" in r.assets
    assert app_update.check("9.0.0", fetch=fetch) is None


def test_check_ignores_prerelease_and_bad_answers():
    def fetch(u, limit):
        return json.dumps({"tag_name": "v9.0.0", "prerelease": True}).encode()
    assert app_update.check("0.1", fetch=fetch) is None
    with pytest.raises(UpdateError):
        app_update.check("0.1", fetch=lambda u, limit: b"<html>")
    with pytest.raises(UpdateError):
        app_update.check("0.1", fetch=lambda u, limit: json.dumps({"tag_name": "v9; rm -rf"}).encode())


def test_foreign_assets_are_ignored():
    fetch, _ = _release(extra=[
        {"name": "evil.exe", "browser_download_url": "https://evil.example/evil.exe", "size": 1},
        {"name": "../x.exe", "browser_download_url": f"{DOWNLOAD_PREFIX}v9.0.0/../x.exe", "size": 1},
    ])
    r = app_update.check("0.1", fetch=fetch)
    assert set(r.assets) == {"SaltMusic-Setup-9.0.0.exe", "SHA256SUMS.txt"}


def test_installer_from_another_place_is_refused(tmp_path):
    fetch, stream = _release(url="https://evil.example/SaltMusic-Setup-9.0.0.exe")
    r = app_update.check("0.1", fetch=fetch)
    with pytest.raises(UpdateError, match="missing"):
        app_update.download(r, "windows", tmp_path, fetch=fetch, stream=stream)


def test_download_verified(tmp_path):
    fetch, stream = _release(digest="sha256:" + hashlib.sha256(INSTALLER).hexdigest())
    r = app_update.check("0.1", fetch=fetch)
    path = app_update.download(r, "windows", tmp_path / "upd", fetch=fetch, stream=stream)
    assert path.read_bytes() == INSTALLER
    assert [p.name for p in path.parent.iterdir()] == [path.name]


def test_download_checksum_mismatch(tmp_path):
    fetch, stream = _release(sums_hash="1" * 64)
    r = app_update.check("0.1", fetch=fetch)
    with pytest.raises(UpdateError, match="mismatch"):
        app_update.download(r, "windows", tmp_path, fetch=fetch, stream=stream)
    assert not list(tmp_path.iterdir())  # nothing half-downloaded is left


def test_download_digest_disagrees(tmp_path):
    fetch, stream = _release(digest="sha256:" + "2" * 64)
    r = app_update.check("0.1", fetch=fetch)
    with pytest.raises(UpdateError, match="disagree"):
        app_update.download(r, "windows", tmp_path, fetch=fetch, stream=stream)


def test_download_missing_from_sums(tmp_path):
    fetch, stream = _release()
    r = app_update.check("0.1", fetch=fetch)
    r.assets["SaltMusic-Setup-9.0.0.run"] = app_update.Asset(
        "SaltMusic-Setup-9.0.0.run", f"{DOWNLOAD_PREFIX}v9.0.0/SaltMusic-Setup-9.0.0.run", 10)
    with pytest.raises(UpdateError):  # listed with a hash nobody can match
        app_update.download(r, "linux", tmp_path, fetch=fetch, stream=stream)
    del r.assets["SHA256SUMS.txt"]
    with pytest.raises(UpdateError, match="SHA256SUMS"):
        app_update.download(r, "windows", tmp_path, fetch=fetch, stream=stream)


def test_stream_size_limit(tmp_path, monkeypatch):
    class Resp:
        headers = {"Content-Length": "0"}

        def __init__(self):
            self.left = 5

        def read(self, n):
            if not self.left:
                return b""
            self.left -= 1
            return b"x" * 100

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(app_update, "_open", lambda url, timeout=30: Resp())
    with pytest.raises(UpdateError, match="too large"):
        app_update._stream("u", tmp_path / "f", 250, None)


def test_install_kind_from_sources():
    # the test run is neither the Inno Setup install nor the .run install
    assert app_update.install_kind() is None


@pytest.mark.skipif(sys.platform == "win32", reason="the Linux updater script")
def test_linux_script_waits_and_installs(tmp_path):
    import subprocess
    import threading

    installer = tmp_path / "fake.run"
    installer.write_text('echo "args: $*" > "$(dirname "$0")/ran"\n')
    prefix = tmp_path / "app dir; echo injected"
    prefix.mkdir()
    (prefix / "salt-music").write_text("#!/bin/sh\necho started > \"$(dirname \"$0\")/started\"\n")
    (prefix / "salt-music").chmod(0o755)
    waiter = subprocess.Popen(["sleep", "0.5"])
    threading.Thread(target=waiter.wait, daemon=True).start()  # reaped like the real app's parent would
    subprocess.run(["/bin/sh", "-c", app_update._LINUX_SCRIPT, "salt-update", str(waiter.pid), str(installer),
                    str(prefix), str(tmp_path / "log")], check=True, timeout=20)
    assert waiter.poll() is not None  # it waited for the app to quit
    assert (tmp_path / "ran").read_text().strip() == f"args: --unattended --prefix {prefix}"
    assert (prefix / "started").exists()


def test_install_kind_on_windows(tmp_path, monkeypatch):
    monkeypatch.setattr(app_update, "IS_WINDOWS", True)
    monkeypatch.setattr(app_update, "app_dir", lambda: tmp_path)
    monkeypatch.setattr(app_update, "FROZEN", False)
    assert app_update.install_kind() is None  # from sources
    monkeypatch.setattr(app_update, "FROZEN", True)
    assert app_update.install_kind() == "portable"
    (tmp_path / "unins001.exe").write_bytes(b"MZ")
    assert app_update.install_kind() == "windows"
    assert app_update.asset_name("1.0", "portable") == app_update.asset_name("1.0", "windows") == "SaltMusic-Setup-1.0.exe"


def test_portable_downloads_the_installer(tmp_path):
    fetch, stream = _release()
    r = app_update.check("0.1", fetch=fetch)
    assert app_update.download(r, "portable", tmp_path, fetch=fetch, stream=stream).name == "SaltMusic-Setup-9.0.0.exe"


def test_open_url_takes_web_links_only(monkeypatch):
    from salt_music import desktop

    opened = []
    monkeypatch.setattr(desktop.webbrowser, "open", lambda url: opened.append(url) or True)
    desktop.open_url("https://github.com/viaqlee/salt-music/releases/tag/v1.0")
    assert opened == ["https://github.com/viaqlee/salt-music/releases/tag/v1.0"]
    for bad in ("file:///C:/Windows/System32/calc.exe", "C:\\evil.exe", "http://example.com"):
        with pytest.raises(ValueError):
            desktop.open_url(bad)
    monkeypatch.setattr(desktop.webbrowser, "open", lambda url: False)
    with pytest.raises(OSError):
        desktop.open_url("https://github.com/")
