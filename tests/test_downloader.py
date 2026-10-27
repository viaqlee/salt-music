import threading
import time
from pathlib import Path

from salt_music import downloader, metadata, naming
from salt_music.config import Settings
from salt_music.downloader import Archive, Downloader, Item, Job, _job_from_dict, _job_to_dict
from salt_music.links import Link


def _job() -> Job:
    rel = metadata.Release("album", "Gruppa krovi", "Kino", "UC" + "a" * 22, "1988", None, 2)
    job = Job(Link("album", "MPREb_x", "https://music.youtube.com/browse/MPREb_x"), "Kino")
    for n, status in ((1, "done"), (2, "downloading")):
        t = metadata.Track(f"vid{n:08}", f"Song {n}", ["Kino"], n)
        it = Item(rel, t, Path("/m/Rock/Kino/Gruppa krovi"), f"0{n}. Song {n}", "Rock", status=status)
        job.items.append(it)
    job.status, job.resolved = "running", True
    return job


def test_job_roundtrip():
    d = _job_to_dict(_job())
    j = _job_from_dict(d)
    assert j.status == "queued"  # was running: resumes after restart
    assert [i.status for i in j.items] == ["done", "queued"]
    assert j.items[0].release is j.items[1].release


def test_archive(tmp_path):
    a = Archive(tmp_path / "archive.txt")
    a.add("abc")
    a.add("abc")
    assert (tmp_path / "archive.txt").read_text() == "youtube abc\n"
    assert "abc" in Archive(tmp_path / "archive.txt")
    a.clear()
    assert "abc" not in Archive(tmp_path / "archive.txt")


class _Recorder:
    def __init__(self, monkeypatch):
        self.calls: list[int] = []
        self.gate = threading.Event()
        rec = self

        def fake_process(self_, job):
            rec.calls.append(job.id)
            rec.gate.wait(5)
            job.status = "done"

        monkeypatch.setattr(Downloader, "_process", fake_process)
        monkeypatch.setattr(downloader, "JOBS_FILE", Path(downloader.JOBS_FILE).with_name("jobs-test.json"))


def _wait(cond, timeout=5.0):
    end = time.monotonic() + timeout
    while not cond():
        if time.monotonic() > end:
            raise AssertionError("timeout")
        time.sleep(0.01)


def test_retry_never_queues_twice(monkeypatch):
    rec = _Recorder(monkeypatch)
    d = Downloader(Settings(), lambda j: None, lambda a: None)
    blocker = d.add(Link("track", "a" * 11, "u1"), "first")  # keeps the worker busy
    _wait(lambda: rec.calls)
    job = d.add(Link("track", "b" * 11, "u2"), "second")
    d.cancel(job)
    d.retry(job)  # the cancelled copy is still waiting in the queue
    d.retry(job)
    rec.gate.set()
    _wait(lambda: blocker.status == "done" and job.status == "done")
    time.sleep(0.2)
    assert rec.calls.count(job.id) == 1


def test_prepare_fits_paths(monkeypatch, tmp_path):
    rec = _Recorder(monkeypatch)
    rec.gate.set()
    s = Settings(music_dir=str(tmp_path), auto_genre=False, manual_genre="Rock")
    d = Downloader(s, lambda j: None, lambda a: None)
    limit = len(str(tmp_path)) + 120  # the temp folder is much deeper on Windows
    monkeypatch.setattr(naming, "PATH_LIMIT", limit)
    rel = metadata.Release("album", "A" * 150, "Kino", None, "", None, 1,
                           [metadata.Track("v" * 11, "T" * 150, ["Kino"], 1)])
    [it] = d._prepare(rel, None)
    full = it.folder / (it.stem + ".opus.part")
    assert len(str(full)) <= limit
    assert it.folder.parent.name == "Kino"


def test_cookie_opts(tmp_path):
    f = tmp_path / "cookies.txt"
    s = Settings(cookies_browser="firefox")
    assert downloader.cookie_opts(s) == {"cookiesfrombrowser": ("firefox",)}
    s.cookies_file = str(f)  # missing file: fall back to the browser
    assert "cookiesfrombrowser" in downloader.cookie_opts(s)
    f.write_text("# Netscape HTTP Cookie File\n", "utf-8")
    assert downloader.cookie_opts(s) == {"cookiefile": str(f)}


def test_cookie_file_status(tmp_path):
    f = tmp_path / "cookies.txt"
    assert downloader.cookie_file_status(str(f)) == "error"
    line = "\t".join([".youtube.com", "TRUE", "/", "TRUE", "2000000000", "{name}", "dummy-test-value"])
    f.write_text("# Netscape HTTP Cookie File\n" + line.format(name="PREF") + "\n", "utf-8")
    assert downloader.cookie_file_status(str(f)) == "anon"
    f.write_text("# Netscape HTTP Cookie File\n" + line.format(name="SAPISID") + "\n", "utf-8")
    assert downloader.cookie_file_status(str(f)) == "ok"
    f.write_bytes(b"\xff\xfe garbage")
    assert downloader.cookie_file_status(str(f)) == "error"


def test_tool_opts_use_found_tools(monkeypatch):
    found = {"ffmpeg": str(Path("/opt/x/bin/ffmpeg")), "deno": str(Path("/opt/d/deno"))}
    monkeypatch.setattr(downloader.tools, "find", lambda n: found.get(n))
    opts = downloader.ytdlp_tool_opts()
    assert opts["ffmpeg_location"] == str(Path("/opt/x/bin"))
    assert opts["js_runtimes"] == {"deno": {"path": found["deno"]}}
