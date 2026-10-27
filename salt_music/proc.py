"""Running external programs (adb, mpv, ffmpeg, PowerShell) the same way everywhere.

On Windows every child gets CREATE_NO_WINDOW (no console flashing over the app),
output is decoded as UTF-8 instead of the ANSI code page (cp1251 would garble
Cyrillic file names coming from adb), and long-lived children are put into a job
object so they die with the app even after a crash.
"""

from __future__ import annotations

import subprocess
import sys

IS_WINDOWS = sys.platform == "win32"
NO_WINDOW = subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0


class Result:
    def __init__(self, returncode: int, stdout: str, stderr: str):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def run(args: list[str], timeout: float = 30, input: str | None = None) -> Result:
    """Run and capture output. Raises FileNotFoundError and subprocess.TimeoutExpired.

    Unlike subprocess.run() this never hangs after a timeout: on Windows run()
    waits for the pipes to close after killing the child, and a daemon the child
    started (``adb start-server``) can keep them open forever.
    """
    with subprocess.Popen(
        args,
        stdin=subprocess.PIPE if input is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        errors="replace",
        creationflags=NO_WINDOW,
    ) as p:
        try:
            out, err = p.communicate(input, timeout=timeout)
        except subprocess.TimeoutExpired:
            p.kill()
            try:
                p.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                pass
            raise
        return Result(p.returncode, out or "", err or "")


def spawn(args: list[str], **kw) -> subprocess.Popen:
    """Start a background child with no console window and no inherited stdio."""
    kw.setdefault("stdin", subprocess.DEVNULL)
    kw.setdefault("stdout", subprocess.DEVNULL)
    kw.setdefault("stderr", subprocess.DEVNULL)
    kw["creationflags"] = kw.get("creationflags", 0) | NO_WINDOW
    if not IS_WINDOWS:
        kw.setdefault("start_new_session", True)
    return subprocess.Popen(args, **kw)


def tie_to_app(p: subprocess.Popen) -> None:
    """Windows: kill `p` when this process exits, however it exits."""
    if IS_WINDOWS:
        _job.assign(p)


class _KillOnCloseJob:
    def __init__(self) -> None:
        self._handle = None

    def assign(self, p: subprocess.Popen) -> None:
        try:
            if self._handle is None:
                self._handle = self._create()
            import ctypes

            ctypes.windll.kernel32.AssignProcessToJobObject(self._handle, int(p._handle))  # type: ignore[attr-defined]
        except (OSError, AttributeError, ValueError):
            pass  # best effort: an orphaned child is not worth failing over

    @staticmethod
    def _create():
        import ctypes
        from ctypes import wintypes

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class BASIC(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class EXTENDED(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", BASIC), ("IoInfo", IO_COUNTERS),
                        ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

        k32 = ctypes.windll.kernel32
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        job = k32.CreateJobObjectW(None, None)
        if not job:
            raise OSError("CreateJobObject failed")
        info = EXTENDED()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):  # Extended info
            raise OSError("SetInformationJobObject failed")
        return job


_job = _KillOnCloseJob()
