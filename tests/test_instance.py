import threading
import time
from multiprocessing.connection import Client

import pytest

from salt_music.desktop import instance


def test_single_instance_and_wake(tmp_path):
    server = instance.claim(tmp_path)
    assert server is not None
    shown = threading.Event()
    server.on_show = shown.set
    try:
        assert instance.claim(tmp_path) is None  # second copy: wakes the first and gives up
        assert shown.wait(5)
    finally:
        server.close()


def test_wrong_key_rejected_server_survives(tmp_path):
    server = instance.claim(tmp_path / "p")
    assert server is not None
    shown = threading.Event()
    server.on_show = shown.set
    addr, family = instance.address(tmp_path / "p")
    try:
        with pytest.raises(Exception):
            with Client(addr, family=family, authkey=b"x" * 32) as c:
                c.send_bytes(instance.MESSAGE)
        time.sleep(0.2)
        assert not shown.is_set()
        assert instance.wake_running(tmp_path / "p")
        assert shown.wait(5)
    finally:
        server.close()


def test_other_messages_ignored(tmp_path):
    server = instance.claim(tmp_path / "q")
    shown = threading.Event()
    server.on_show = shown.set
    addr, family = instance.address(tmp_path / "q")
    try:
        with Client(addr, family=family, authkey=instance._key(tmp_path / "q")) as c:
            c.send_bytes(b"exec something")
        time.sleep(0.3)
        assert not shown.is_set()
    finally:
        server.close()


def test_profiles_are_separate(tmp_path):
    a = instance.claim(tmp_path / "a")
    b = instance.claim(tmp_path / "b")
    try:
        assert a is not None and b is not None
    finally:
        a.close()
        b.close()
