import shlex
from pathlib import Path

import pytest

from salt_music import adb


@pytest.mark.parametrize("addr", ["192.168.1.5:5555", "phone.local:37001", "[fe80::1]:5555"])
def test_good_addresses(addr):
    assert adb.ADDRESS_RE.match(addr)


@pytest.mark.parametrize("addr", ["", "1.2.3.4", "-s evil:1", "a:1; rm -rf /", "host:99999999", "a b:1", "--help:1"])
def test_bad_addresses(addr, monkeypatch):
    monkeypatch.setattr(adb, "_run", lambda *a, **k: pytest.fail("adb must not run"))
    with pytest.raises(adb.AdbError, match="bad_address"):
        adb.connect(addr)


def test_remote_rel_reuses_existing_case(tmp_path):
    f = tmp_path / "Rock" / "Kino" / "Album" / "01. Song.opus"
    real, rel = adb._remote_rel(f, tmp_path, {"rock": "ROCK", "rock/kino": "ROCK/kino"})
    assert real == ["ROCK", "kino", "Album"]
    assert rel == "ROCK/kino/Album/01. Song.opus"


def test_push_quotes_everything(tmp_path, monkeypatch):
    calls: list[list[str]] = []

    def fake_run(args, timeout=30):
        calls.append(args)
        if args[2] == "shell" and args[3].startswith("find "):
            return "/sdcard/Music $(x)/Rock/Kino/01. old.opus\n"
        return ""

    monkeypatch.setattr(adb, "_run", fake_run)
    base = tmp_path
    d = base / "Rock" / "Kino"
    d.mkdir(parents=True)
    files = [d / "01. old.opus", d / "02. it's $(new).opus"]
    for f in files:
        f.write_bytes(b"x")
    progress = []
    sent, skipped = adb.push("SERIAL", base, files, "/sdcard/Music $(x)/",
                             lambda i, n, f, s: progress.append(s))
    assert (sent, skipped) == (1, 1)
    shells = [a[3] for a in calls if a[2] == "shell"]
    for cmd in shells:
        # every variable part is one shell word: nothing gets expanded on the phone
        assert "$(x)" not in cmd.replace(shlex.quote("/sdcard/Music $(x)"), "") \
            .replace(shlex.quote("/sdcard/Music $(x)/Rock/Kino"), "") \
            .replace(shlex.quote("file:///sdcard/Music $(x)"), "")
    push = next(a for a in calls if a[2] == "push")
    assert push[3:] == [str(files[1]), "/sdcard/Music $(x)/Rock/Kino/02. it's $(new).opus"]
    assert progress[-1] == "sent"


def test_devices_parsing(monkeypatch):
    out = ("List of devices attached\n"
           "R58M123 device usb:1-1 product:x model:Galaxy_S10 device:beyond1\n"
           "192.168.1.5:5555 unauthorized\n"
           "XYZ no permissions (user in plugdev group)\n\n")
    monkeypatch.setattr(adb, "_run", lambda *a, **k: out)
    d = adb.devices()
    assert [(x.serial, x.state, x.model) for x in d] == [
        ("R58M123", "device", "Galaxy S10"), ("192.168.1.5:5555", "unauthorized", ""),
        ("XYZ", "no permissions", "")]


def test_missing_adb(monkeypatch):
    monkeypatch.setattr(adb.tools, "find", lambda n: None)
    with pytest.raises(adb.AdbError, match="adb_missing"):
        adb.devices()


@pytest.mark.parametrize("typed, path", [
    ("/sdcard/Music", "/sdcard/Music"), ("/sdcard/Music/", "/sdcard/Music"),
    ("sdcard\\Music\\", "/sdcard/Music"), (" \\sdcard\\Музыка ", "/sdcard/Музыка"), ("/", "/"), ("", "/")])
def test_remote_path_from_windows_input(typed, path):
    assert adb.remote_path(typed) == path


def test_push_survives_unreadable_folders(tmp_path, monkeypatch):
    """find exits with 1 on Android/data under /sdcard: the listing must still be used."""
    calls: list[str] = []

    def fake_run(args, timeout=30):
        if args[2] == "shell":
            calls.append(args[3])
        return "/sdcard/Rock/01. a.opus\n" if args[3].startswith("find ") else ""

    monkeypatch.setattr(adb, "_run", fake_run)
    f = tmp_path / "Rock" / "01. a.opus"
    f.parent.mkdir()
    f.write_bytes(b"x")
    assert adb.push("S", tmp_path, [f], "sdcard\\", lambda *a: None) == (0, 1)
    find = next(c for c in calls if c.startswith("find "))
    assert find == "find /sdcard 2>/dev/null; true"
