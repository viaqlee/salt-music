"""Tags and library on real audio files made by ffmpeg."""

import io
import os

import pytest
from PIL import Image

from salt_music import library, tagger
from conftest import audio_file


def _png(w, h) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (w, h), (200, 30, 30)).save(out, "PNG")
    return out.getvalue()


@pytest.mark.parametrize("ext", ["opus", "m4a", "mp3", "flac"])
def test_tag_roundtrip(tmp_path, ext):
    folder = tmp_path / "Rock" / "Кино" / "Группа крови"
    folder.mkdir(parents=True)
    f = audio_file(folder, ext)
    cover = tagger.square_jpeg(_png(320, 180))
    tagger.write(f, tagger.Tags("Группа крови", "Кино", "Кино", "Группа крови", "Rock", "1988", 1, 11), cover)
    t = library.read(f)
    assert (t.title, t.artist, t.album, t.number) == ("Группа крови", "Кино", "Группа крови", 1)
    got = tagger.read_cover(f)
    assert got and Image.open(io.BytesIO(got)).size == (180, 180)
    [artist] = library.scan(tmp_path)
    assert artist.name == "Кино" and len(artist.tracks) == 1


def test_info_cache_follows_changes(tmp_path):
    f = audio_file(tmp_path, "opus")
    tagger.write(f, tagger.Tags("One", "A", "A", "X", "Rock"), None)
    assert library.read(f).title == "One"
    tagger.write(f, tagger.Tags("Two", "A", "A", "X", "Rock"), None)
    st = f.stat()
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))  # coarse clocks
    assert library.read(f).title == "Two"


def test_square_jpeg_limits():
    assert tagger.square_jpeg(b"not an image") is None
    old = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = 100
    try:
        assert tagger.square_jpeg(_png(20, 20)) is None  # decompression bomb guard
    finally:
        Image.MAX_IMAGE_PIXELS = old
    big = tagger.square_jpeg(_png(2000, 1500))
    assert Image.open(io.BytesIO(big)).size == (1200, 1200)


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://x/y", "javascript:1", "", "C:\\Windows\\win.ini"])
def test_fetch_rejects_other_schemes(url):
    assert tagger.fetch(url) is None


def test_broken_file_does_not_break_scan(tmp_path):
    d = tmp_path / "G" / "Artist" / "Album"
    d.mkdir(parents=True)
    (d / "01. broken.mp3").write_bytes(b"\x00" * 100)
    [a] = library.scan(tmp_path)
    assert a.tracks[0].title == "01. broken"
