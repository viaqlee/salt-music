"""Every test run gets its own profile: the user's real settings are never touched."""

import os
import sys
import tempfile
from pathlib import Path

_HOME = tempfile.mkdtemp(prefix="salt-test-")
os.environ["SALT_MUSIC_HOME"] = _HOME
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from salt_music import tools  # noqa: E402


def audio_file(folder: Path, ext: str, seconds: float = 1.0) -> Path:
    """A short real audio file made by ffmpeg (tests needing it skip without ffmpeg)."""
    import subprocess

    ffmpeg = tools.find(tools.FFMPEG)
    if not ffmpeg:
        pytest.skip("ffmpeg not available")
    codec = {"opus": ["-c:a", "libopus"], "m4a": ["-c:a", "aac"], "mp3": ["-c:a", "libmp3lame"],
             "flac": ["-c:a", "flac"]}[ext]
    out = folder / f"tone.{ext}"
    subprocess.run([ffmpeg, "-v", "error", "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
                    *codec, "-y", str(out)], check=True, timeout=60)
    return out


@pytest.fixture
def home() -> Path:
    return Path(_HOME)
