from pathlib import Path

from salt_music import naming


def test_clean_forbidden_and_reserved():
    assert naming.clean('AC/DC: "Back" <in> Black?') == "AC_DC_ _Back_ _in_ Black_"
    assert naming.clean("CON") == "_CON"
    assert naming.clean("nul.txt") == "_nul.txt"
    assert naming.clean("COM¹") == "_COM¹"
    assert naming.clean("CONIN$") == "_CONIN$"
    assert naming.clean("Console") == "Console"
    assert naming.clean("  ...  ") == "Unknown"
    assert naming.clean("name. ") == "name"


def test_clean_cuts_utf8_bytes():
    name = naming.clean("я" * 300)
    assert len(name.encode()) <= naming.STEM_BYTES
    assert name == "я" * (naming.STEM_BYTES // 2)


def test_render_and_resolve(tmp_path):
    parts = naming.render("{genre}/{artist}/{year} — {album}", {"genre": "Rock", "artist": "Kino", "album": "Gruppa krovi", "year": ""})
    assert parts == ["Rock", "Kino", "Gruppa krovi"]
    (tmp_path / "rock").mkdir()
    assert naming.resolve_dir(tmp_path, parts).parent.parent.name == "rock"


def _u16(s):
    return len(s.encode("utf-16-le")) // 2


def test_fit_keeps_short_paths():
    parts, stem = naming.fit(Path("C:/Music"), ["Rock", "Kino"], "01. Song", limit=240)
    assert parts == ["Rock", "Kino"] and stem == "01. Song"


def test_fit_long_path_same_folder_for_every_track():
    base = Path("/m" + "x" * 60)
    parts = ["Genre", "A" * 150, "B" * 150]
    p1, s1 = naming.fit(base, parts, "01. " + "t" * 200, limit=240)
    p2, s2 = naming.fit(base, parts, "02. short", limit=240)
    assert p1 == p2  # an album never splits into two folders
    for p, s in ((p1, s1), (p2, s2)):
        total = _u16(str(base)) + sum(_u16(x) + 1 for x in p) + 1 + _u16(s) + 20
        assert total <= 240
        assert len(s) >= min(naming.STEM_MIN, len("02. short"))
    assert s2 == "02. short"


def test_fit_handles_surrogates():
    _, stem = naming.fit(Path("/m"), ["a" * 150], "🎵" * 100, limit=240)
    stem.encode("utf-8")  # no broken surrogate halves
    assert _u16(stem) <= 240 - 20 - 1 - _u16("/m") - 151
