import hashlib
import io
import json
import sys
import zipfile

import pytest

from salt_music import updater
from salt_music.updater import UpdateError


def _wheel(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, text in files.items():
            z.writestr(name, text)
    return buf.getvalue()


def _fake_pypi(version="2099.1.1", ytdlp_files=None, host="https://files.pythonhosted.org/", tamper=False):
    wheels = {
        "yt-dlp": _wheel(ytdlp_files or {"yt_dlp/__init__.py": "VERSION = 'fake'\n"}),
        "yt-dlp-ejs": _wheel({"yt_dlp_ejs/__init__.py": ""}),
    }
    urls = {f"{host}{n}.whl": w for n, w in wheels.items()}

    def fetch(url, limit):
        for name, w in wheels.items():
            if url == updater.PYPI.format(name=name):
                return json.dumps({"info": {"version": version, "requires_python": ">=3.10"}, "urls": [{
                    "packagetype": "bdist_wheel", "filename": f"{name}-{version}-py3-none-any.whl",
                    "url": f"{host}{name}.whl", "digests": {"sha256": hashlib.sha256(w).hexdigest()},
                }]}).encode()
        data = urls[url]
        return data + b"x" if tamper else data
    return fetch


def test_update_activate_reset(tmp_path):
    v = updater.update("2026.1.1", root=tmp_path, fetch=_fake_pypi())
    assert v == "2099.1.1"
    assert (tmp_path / v / "yt_dlp" / "__init__.py").is_file()
    assert (tmp_path / v / "yt_dlp_ejs").is_dir()
    assert updater.active_version(tmp_path) == v
    (tmp_path / "2000.0.0").mkdir()  # an old version is cleaned up at start
    try:
        assert updater.activate(tmp_path) == v
        assert sys.path[0] == str(tmp_path / v)
    finally:
        sys.path.remove(str(tmp_path / v))
    assert not (tmp_path / "2000.0.0").exists()
    assert updater.update(v, root=tmp_path, fetch=_fake_pypi()) is None
    updater.reset(tmp_path)
    assert updater.activate(tmp_path) is None


def test_checksum_mismatch(tmp_path):
    with pytest.raises(UpdateError, match="checksum"):
        updater.update("1", root=tmp_path, fetch=_fake_pypi(tamper=True))
    assert updater.active_version(tmp_path) is None
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".staging")]


def test_path_traversal_rejected(tmp_path):
    bad = {"yt_dlp/__init__.py": "", "../../evil.py": "x"}
    with pytest.raises(UpdateError, match="bad path"):
        updater.update("1", root=tmp_path / "pk", fetch=_fake_pypi(ytdlp_files=bad))
    assert not (tmp_path / "evil.py").exists()


def test_foreign_host_rejected(tmp_path):
    with pytest.raises(UpdateError, match="unexpected"):
        updater.update("1", root=tmp_path, fetch=_fake_pypi(host="https://evil.example/"))


def test_bad_pointer_ignored(tmp_path):
    (tmp_path / updater.POINTER).write_text("../../etc", "utf-8")
    assert updater.activate(tmp_path) is None


def test_requires_python():
    assert updater._requires_ok(">=3.10")
    assert not updater._requires_ok(">=4.0")
    assert updater._requires_ok(None)
