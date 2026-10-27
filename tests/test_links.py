import pytest

from salt_music import links
from salt_music.links import LinkError


@pytest.mark.parametrize("url,kind", [
    ("https://music.youtube.com/watch?v=dQw4w9WgXcQ", "track"),
    ("youtu.be/dQw4w9WgXcQ", "track"),
    ("https://music.youtube.com/browse/MPREb_abcdefghij", "album"),
    ("https://www.youtube.com/channel/UC" + "a" * 22, "artist"),
])
def test_parse(url, kind):
    assert links.parse(url).kind == kind


@pytest.mark.parametrize("url,err", [
    ("", "err_link_empty"),
    ("https://evil.example.com/watch?v=dQw4w9WgXcQ", "err_link_host"),
    ("https://youtube.com.evil.example/watch?v=dQw4w9WgXcQ", "err_link_host"),
    ("file:///etc/passwd", "err_link_host"),
])
def test_reject(url, err):
    with pytest.raises(LinkError) as e:
        links.parse(url)
    assert str(e.value) == err
