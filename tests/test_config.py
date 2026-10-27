import json

from salt_music import config
from salt_music.config import History, JsonStore, Settings, _write_json


def test_load_untrusted_types(tmp_path):
    f = tmp_path / "settings.json"
    f.write_text(json.dumps({
        "language": "de", "audio_format": "wav", "sleep_between": 1e9, "phone_width": "wide",
        "auto_genre": "yes", "templates": {"album": 5, "ep": "{artist}", "bogus": "x"},
        "cookies_browser": "librewolf", "music_dir": "", "phone_dir": "relative", "unknown": 1,
        "filename_template": "  ",
    }), "utf-8")
    s = Settings.load(f)
    assert s.language == "ru" and s.audio_format == "opus"
    assert s.sleep_between == config.MAX_SLEEP
    assert s.phone_width == 320 and s.auto_genre is True
    assert s.templates["album"] == config.DEFAULT_TEMPLATES["album"]
    assert s.templates["ep"] == "{artist}" and "bogus" not in s.templates
    assert s.cookies_browser == "" and s.music_dir and s.phone_dir == config.PHONE_DIR
    assert s.filename_template == config.DEFAULT_FILENAME


def test_load_garbage(tmp_path):
    f = tmp_path / "settings.json"
    f.write_text("[1, 2", "utf-8")
    assert Settings.load(f) == Settings()
    f.write_text("[1, 2]", "utf-8")
    assert Settings.load(f) == Settings()


def test_roundtrip(tmp_path):
    f = tmp_path / "s.json"
    s = Settings(cookies_file="C:/x/cookies.txt", sleep_between=3.5)
    s.save(f)
    assert Settings.load(f) == s


def test_browsers_supported_by_ytdlp():
    from yt_dlp.cookies import SUPPORTED_BROWSERS

    assert set(config.BROWSERS) - {""} <= set(SUPPORTED_BROWSERS)


def test_write_json_atomic(tmp_path):
    f = tmp_path / "a" / "x.json"
    for i in range(20):
        _write_json(f, {"i": i, "текст": "ё"})
    assert json.loads(f.read_text("utf-8")) == {"i": 19, "текст": "ё"}
    assert [p.name for p in f.parent.iterdir()] == ["x.json"]  # no temp files left


def test_stores_ignore_wrong_shape(tmp_path):
    f = tmp_path / "h.json"
    f.write_text('{"not": "a list"}', "utf-8")
    h = History(f)
    assert h.items == []
    h.add({"title": "x"})
    assert History(f).items == [{"title": "x"}]
    g = tmp_path / "g.json"
    g.write_text("[1]", "utf-8")
    assert JsonStore(g).data == {}
