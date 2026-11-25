# 读取 AGYS_STUB_TARGET 指定的凭据条目并打印 blob 文本（测试专用）
import ctypes
import ctypes.wintypes as wt
import os
import sys

target = os.environ["AGYS_STUB_TARGET"]
advapi = ctypes.WinDLL("Advapi32", use_last_error=True)


class CREDENTIAL(ctypes.Structure):
    _fields_ = [("Flags", wt.DWORD), ("Type", wt.DWORD), ("TargetName", wt.LPWSTR),
                ("Comment", wt.LPWSTR), ("LastWritten", wt.FILETIME),
                ("CredentialBlobSize", wt.DWORD),
                ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)),
                ("Persist", wt.DWORD), ("AttributeCount", wt.DWORD),
                ("Attributes", ctypes.c_void_p), ("TargetAlias", wt.LPWSTR),
                ("UserName", wt.LPWSTR)]


p = ctypes.POINTER(CREDENTIAL)()
if not advapi.CredReadW(target, 1, 0, ctypes.byref(p)):
    print("ABSENT")
    sys.exit(0)
c = p[0]
raw = bytes(bytearray(c.CredentialBlob[:c.CredentialBlobSize]))
print(raw.decode("utf-8", errors="replace"))
