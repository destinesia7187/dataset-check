from __future__ import annotations

import ctypes
import json
import os
import signal
import sys
import threading
from pathlib import Path


class InstanceLock:
    def __init__(self, path):
        self.file = Path(path).open("a+b")
        self.file.seek(0)
        self.file.write(b"0")
        self.file.flush()
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise RuntimeError(
                "This directory is already in use by another Dataset Check process"
            ) from None

    def close(self):
        self.file.close()


def guard_parent(parent_pid):
    """OS parent death protection plus a portable watchdog for the startup race."""
    if sys.platform.startswith("linux"):
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(1, signal.SIGKILL) != 0:
            raise RuntimeError("Cannot set parent-death signal")
        if os.getppid() != parent_pid:
            os._exit(71)
    if os.name == "nt":
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        parent = kernel.OpenProcess(0x00100000, False, parent_pid)
        if not parent:
            os._exit(71)

        def watch():
            kernel.WaitForSingleObject(parent, 0xFFFFFFFF)
            kernel.CloseHandle(parent)
            os._exit(71)
    else:

        def watch():
            import time

            while os.getppid() == parent_pid:
                time.sleep(0.1)
            os._exit(71)

    threading.Thread(target=watch, daemon=True, name="parent-watchdog").start()


def process_identity(pid):
    if os.name == "nt":
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [
            ctypes.POINTER(wintypes.FILETIME)
        ] * 4
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return None
        created, exited, kernel_time, user_time = (wintypes.FILETIME() for _ in range(4))
        status = wintypes.DWORD()
        try:
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(status)) or status.value != 259:
                return None
            if not kernel.GetProcessTimes(
                handle,
                ctypes.byref(created),
                ctypes.byref(exited),
                ctypes.byref(kernel_time),
                ctypes.byref(user_time),
            ):
                return None
            return str((created.dwHighDateTime << 32) | created.dwLowDateTime)
        finally:
            kernel.CloseHandle(handle)
    try:
        stat = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        if stat[0] == "Z":
            return None
        return stat[19]
    except (FileNotFoundError, ProcessLookupError):
        return None


def stop_orphan(root):
    path = Path(root) / "active_worker.json"
    if not path.exists():
        return
    entry = json.loads(path.read_text("utf-8"))
    pid = entry.get("pid")
    birth = entry.get("identity")
    if isinstance(pid, int) and birth and process_identity(pid) == birth:
        if os.name == "nt":
            from ctypes import wintypes

            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
            kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            handle = kernel.OpenProcess(0x00100001, False, pid)
            if not handle:
                raise RuntimeError("Cannot confirm termination of previous worker")
            try:
                kernel.TerminateProcess(handle, 71)
                kernel.WaitForSingleObject(handle, 5000)
            finally:
                kernel.CloseHandle(handle)
        else:
            os.kill(pid, signal.SIGKILL)
        if process_identity(pid) == birth:
            raise RuntimeError("Previous worker is still alive")
    path.unlink(missing_ok=True)
