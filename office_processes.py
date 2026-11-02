"""Hold exact process handles for new Office instances identified by the helper.

The helper reports only the PID behind its COM instance's HWND and excludes
Office processes that existed before activation. Never kill by executable name.
"""

import ctypes
import logging
import os
from ctypes import wintypes

logger = logging.getLogger(__name__)


class OwnedOfficeProcesses:
    def __init__(self):
        self.handles = []
        self.kernel = None
        if os.name == "nt":
            self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            self.kernel.OpenProcess.argtypes = [
                wintypes.DWORD,
                wintypes.BOOL,
                wintypes.DWORD,
            ]
            self.kernel.OpenProcess.restype = wintypes.HANDLE
            self.kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
            self.kernel.TerminateProcess.restype = wintypes.BOOL
            self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            self.kernel.CloseHandle.restype = wintypes.BOOL
            self.kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            self.kernel.WaitForSingleObject.restype = wintypes.DWORD
            self.kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [
                ctypes.POINTER(wintypes.FILETIME)
            ] * 4
            self.kernel.GetProcessTimes.restype = wintypes.BOOL

    def register(self, pid: int, creation_time: int) -> None:
        if self.kernel and pid > 0:
            # Retain the original instance, even if its PID is later recycled.
            handle = self.kernel.OpenProcess(0x00101001, False, pid)
            if handle:
                created, exited, kernel, user = (wintypes.FILETIME() for _ in range(4))
                success = self.kernel.GetProcessTimes(
                    handle,
                    ctypes.byref(created),
                    ctypes.byref(exited),
                    ctypes.byref(kernel),
                    ctypes.byref(user),
                )
                actual = created.dwLowDateTime | (created.dwHighDateTime << 32)
                if success and actual == creation_time:
                    self.handles.append(handle)
                else:
                    self.kernel.CloseHandle(handle)
                    logger.warning(
                        "Office process identity no longer matches: pid=%s", pid
                    )
            else:
                logger.warning(
                    "Could not retain owned Office process handle: pid=%s", pid
                )

    def close(self) -> None:
        if self.kernel:
            for handle in self.handles:
                try:
                    if self.kernel.WaitForSingleObject(handle, 0) == 258:
                        if not self.kernel.TerminateProcess(handle, 1):
                            logger.warning(
                                "Owned Office process did not exit: error=%s",
                                ctypes.get_last_error(),
                            )
                        else:
                            self.kernel.WaitForSingleObject(handle, 5000)
                finally:
                    self.kernel.CloseHandle(handle)
        self.handles.clear()
