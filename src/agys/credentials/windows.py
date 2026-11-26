"""Windows Credential Manager 后端（ctypes 直调，不经 PowerShell/cmdkey）。"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt

from . import CredentialError, CredentialStore

CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2
ERROR_NOT_FOUND = 1168

_advapi = ctypes.WinDLL("Advapi32", use_last_error=True)


class _CREDENTIAL(ctypes.Structure):
    _fields_ = [
        ("Flags", wt.DWORD), ("Type", wt.DWORD), ("TargetName", wt.LPWSTR),
        ("Comment", wt.LPWSTR), ("LastWritten", wt.FILETIME),
        ("CredentialBlobSize", wt.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)),
        ("Persist", wt.DWORD), ("AttributeCount", wt.DWORD),
        ("Attributes", ctypes.c_void_p), ("TargetAlias", wt.LPWSTR),
        ("UserName", wt.LPWSTR),
    ]


class WindowsStore(CredentialStore):
    name = "windows-credential-manager"

    def __init__(self, target: str, user: str):
        self.target = target
        self.user = user

    def describe(self) -> str:
        return f"{self.name} ({self.target})"

    def get(self):
        p = ctypes.POINTER(_CREDENTIAL)()
        if not _advapi.CredReadW(self.target, CRED_TYPE_GENERIC, 0, ctypes.byref(p)):
            err = ctypes.get_last_error()
            if err == ERROR_NOT_FOUND:
                return None
            raise CredentialError(f"CredReadW 失败 (winerror={err})")
        try:
            c = p[0]
            return ctypes.string_at(c.CredentialBlob, c.CredentialBlobSize)
        finally:
            _advapi.CredFree(p)

    def set(self, blob: bytes):
        c = _CREDENTIAL()
        c.Flags = 0
        c.Type = CRED_TYPE_GENERIC
        c.TargetName = self.target
        c.UserName = self.user
        c.Persist = CRED_PERSIST_LOCAL_MACHINE
        c.CredentialBlobSize = len(blob)
        c.CredentialBlob = ctypes.cast(
            ctypes.create_string_buffer(blob, len(blob)),
            ctypes.POINTER(ctypes.c_byte))
        if not _advapi.CredWriteW(ctypes.byref(c), 0):
            raise CredentialError(f"CredWriteW 失败 (winerror={ctypes.get_last_error()})")

    def delete(self):
        if not _advapi.CredDeleteW(self.target, CRED_TYPE_GENERIC, 0):
            err = ctypes.get_last_error()
            if err != ERROR_NOT_FOUND:
                raise CredentialError(f"CredDeleteW 失败 (winerror={err})")


def list_targets(filter_prefix=None):
    """枚举凭据条目名（只读 TargetName，不读取 blob）。"""
    count = wt.DWORD(0)
    pcreds = ctypes.POINTER(ctypes.POINTER(_CREDENTIAL))()
    if not _advapi.CredEnumerateW(filter_prefix, 0, ctypes.byref(count),
                                  ctypes.byref(pcreds)):
        err = ctypes.get_last_error()
        if err == ERROR_NOT_FOUND:
            return []
        raise CredentialError(f"CredEnumerateW 失败 (winerror={err})")
    try:
        out = []
        for i in range(count.value):
            cred = pcreds[i][0]
            if cred.TargetName:
                out.append(cred.TargetName)
        return out
    finally:
        _advapi.CredFree(pcreds)
