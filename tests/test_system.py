"""proc, tools, mpv IPC parsing, i18n."""

import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

from salt_music import audio, i18n, proc, tools


def test_run_utf8_output():
    r = proc.run([sys.executable, "-c", "import sys; sys.stdout.buffer.write('Кино ♪'.encode())"])
    assert r.returncode == 0 and r.stdout == "Кино ♪"


def test_run_timeout_kills():
    start = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        proc.run([sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.5)
    assert time.monotonic() - start < 10


def test_spawn_has_no_pipes():
    p = proc.spawn([sys.executable, "-c", "print('x')"])
    assert p.stdout is None and p.stdin is None
    assert p.wait(10) == 0


def test_tools_find_and_hint(monkeypatch, tmp_path):
    exe = tmp_path / ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
    exe.write_text("")
    exe.chmod(0o755)
    monkeypatch.setattr(tools, "search_dirs", lambda: [tmp_path])
    monkeypatch.setenv("PATH", "")
    tools.refresh()
    try:
        assert tools.find(tools.FFMPEG) == str(exe)
        assert tools.find("definitely-not-a-tool") is None
    finally:
        tools.refresh()
    for name in (tools.FFMPEG, tools.DENO, tools.MPV, tools.ADB):
        assert tools.install_hint(name)


class _Events(list):
    def __call__(self, name, value):
        self.append((name, value))


def test_mpv_messages_parsing():
    ev = _Events()
    m = audio.Mpv(ev)
    m._on_data(b'{"event":"property-change","name":"time-pos","data":1.5}\n{"event":"prop')
    m._on_data(b'erty-change","name":"duration","data":200}\nnot json\n[1,2]\n')
    m._on_data(b'{"event":"property-change","name":"time-pos","data":"evil"}\n')
    m._on_data(b'{"event":"property-change","name":"time-pos","data":1.6}\n')  # < 0.25s later: dropped
    m._on_data(b'{"event":"property-change","name":"pause","data":true}\n{"event":"end-file","reason":"eof"}\n')
    assert ev == [("position", 1.5), ("duration", 200.0), ("paused", True), ("ended", None)]
    m._on_data(b"x" * (2 << 20))  # garbage with no newline is dropped, not kept forever
    assert len(m._buf) < (1 << 20) + 1


def test_mpv_handler_errors_do_not_kill_reader():
    def boom(name, value):
        raise RuntimeError("ui")
    m = audio.Mpv(boom)
    m._on_data(b'{"event":"end-file","reason":"eof"}\n')


@pytest.mark.skipif(not audio.available(), reason="mpv not installed")
def test_mpv_real_process(tmp_path):
    from conftest import audio_file

    f = audio_file(tmp_path, "opus", seconds=2)
    ev = _Events()
    m = audio.Mpv(ev)
    try:
        m.set_volume(0)
        m.load(str(f))
        end = time.monotonic() + 15
        while ("ended", None) not in ev and time.monotonic() < end:
            time.sleep(0.05)
        assert any(n == "duration" for n, _ in ev)
        assert ("ended", None) in ev
    finally:
        m.stop()
    assert m._proc is None


def test_i18n_pairs_and_placeholders():
    fields = re.compile(r"{(\w*)}")
    for key, pair in {**i18n.STRINGS, **i18n.WINDOWS}.items():
        assert isinstance(pair, tuple) and len(pair) == 2, key
        assert set(fields.findall(pair[0])) == set(fields.findall(pair[1])), key
    for key in i18n.WINDOWS:
        assert key in i18n.STRINGS, key


def test_i18n_every_used_key_exists():
    root = Path(__file__).resolve().parents[1] / "salt_music"
    used = set()
    for py in root.rglob("*.py"):
        used |= set(re.findall(r"""\bt\(\s*["']([a-z0-9_]+)["']""", py.read_text("utf-8")))
    # "err_" + code and the like are prefixes, checked where the codes are made
    missing = sorted(k for k in used if k not in i18n.STRINGS and not k.endswith("_"))
    assert not missing, missing


def test_i18n_tool_hint_filled():
    i18n.set_language("en")
    try:
        text = i18n.t("ffmpeg_missing")
        assert "{cmd}" not in text and tools.install_hint(tools.FFMPEG) in text
        assert i18n.t("no_such_key") == "no_such_key"
    finally:
        i18n.set_language("ru")


def test_tool_installed_later_is_found(monkeypatch, tmp_path):
    monkeypatch.setattr(tools, "search_dirs", lambda: [tmp_path])
    monkeypatch.setenv("PATH", "")
    tools.refresh()
    clock = [1000.0]
    monkeypatch.setattr(tools.time, "monotonic", lambda: clock[0])
    try:
        assert tools.find(tools.MPV) is None
        exe = tmp_path / ("mpv.exe" if sys.platform == "win32" else "mpv")
        exe.write_text("")
        exe.chmod(0o755)
        assert tools.find(tools.MPV) is None  # a miss is remembered for a while
        clock[0] += tools.MISS_TTL + 1
        assert tools.find(tools.MPV) == str(exe)
    finally:
        tools.refresh()


def test_tool_chosen_by_hand(monkeypatch, tmp_path):
    exe_name = lambda n: n + ".exe" if sys.platform == "win32" else n  # noqa: E731
    monkeypatch.setattr(tools, "search_dirs", lambda: [])
    monkeypatch.setenv("PATH", "")
    folder = tmp_path / "my ffmpeg"
    (folder / "bin").mkdir(parents=True)
    ffmpeg, ffprobe = folder / "bin" / exe_name("ffmpeg"), folder / "bin" / exe_name("ffprobe")
    for f in (ffmpeg, ffprobe):
        f.write_text("")
        f.chmod(0o755)
    try:
        tools.set_custom({"ffmpeg": str(ffmpeg)})
        assert tools.find(tools.FFMPEG) == str(ffmpeg)
        assert tools.find(tools.FFPROBE) == str(ffprobe)  # follows ffmpeg
        tools.set_custom({"ffmpeg": str(folder)})  # a folder works too, bin inside is looked into
        assert tools.find(tools.FFMPEG) == str(ffmpeg)
        tools.set_custom({"ffmpeg": str(tmp_path / "gone.exe")})
        assert tools.custom_status(tools.FFMPEG) == (str(tmp_path / "gone.exe"), None)
        assert tools.find(tools.FFMPEG) is None
        tools.set_custom({"ffmpeg": "relative/ffmpeg", "rm": "/bin/rm"})  # relative and unknown: ignored
        assert tools.custom_status(tools.FFMPEG)[1] is None
        assert "rm" not in tools._custom
    finally:
        tools.set_custom({})


def test_winget_package_folders(tmp_path):
    deep = tmp_path / "Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe" / "ffmpeg-8.0-full_build" / "bin"
    deep.mkdir(parents=True)
    (deep / "ffmpeg.exe").write_text("")
    too_deep = tmp_path / "Other" / "a" / "b" / "c" / "d"
    too_deep.mkdir(parents=True)
    (too_deep / "adb.exe").write_text("")
    assert tools._winget_package_dirs(tmp_path) == [deep]
    assert tools._winget_package_dirs(tmp_path / "missing") == []


def test_settings_keep_only_known_tools():
    from salt_music.config import Settings

    s = Settings.from_dict({"tool_paths": {"ffmpeg": " /opt/ff/ffmpeg ", "evil": "/bin/sh", "adb": 5, "mpv": ""}})
    assert s.tool_paths == {"ffmpeg": "/opt/ff/ffmpeg"}
    assert Settings.from_dict({"tool_paths": "x"}).tool_paths == {}
