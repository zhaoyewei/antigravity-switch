# 测试桩：模拟 agy 的登录行为。
# 读取环境变量：AGYS_STUB_TARGET（凭据条目名）、AGYS_STUB_EMAIL、AGYS_STUB_BLOB、
# AGYS_STUB_GEMINI_HOME、AGYS_STUB_ARGS_FILE；把凭据写入 Windows 凭据库并写
# google_accounts.json，把收到的命令行参数记录到 AGYS_STUB_ARGS_FILE。
import ctypes
import ctypes.wintypes as wt
import json
import os
import sys

target = os.environ["AGYS_STUB_TARGET"]
blob = os.environ["AGYS_STUB_BLOB"].encode("utf-8")
email = os.environ["AGYS_STUB_EMAIL"]
ga_home = os.environ["AGYS_STUB_GEMINI_HOME"]

advapi = ctypes.WinDLL("Advapi32", use_last_error=True)


class CREDENTIAL(ctypes.Structure):
    _fields_ = [("Flags", wt.DWORD), ("Type", wt.DWORD), ("TargetName", wt.LPWSTR),
                ("Comment", wt.LPWSTR), ("LastWritten", wt.FILETIME),
                ("CredentialBlobSize", wt.DWORD),
                ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)),
                ("Persist", wt.DWORD), ("AttributeCount", wt.DWORD),
                ("Attributes", ctypes.c_void_p), ("TargetAlias", wt.LPWSTR),
                ("UserName", wt.LPWSTR)]


c = CREDENTIAL()
c.Type = 1
c.TargetName = target
c.UserName = "antigravity"
c.Persist = 2
c.CredentialBlobSize = len(blob)
c.CredentialBlob = ctypes.cast(ctypes.create_string_buffer(blob, len(blob)),
                               ctypes.POINTER(ctypes.c_byte))
ok = advapi.CredWriteW(ctypes.byref(c), 0)
if not ok:
    print("stub: CredWriteW failed", ctypes.get_last_error())
    sys.exit(2)

os.makedirs(ga_home, exist_ok=True)
with open(os.path.join(ga_home, "google_accounts.json"), "w", encoding="utf-8") as f:
    json.dump({"active": email, "old": []}, f)

args_file = os.environ.get("AGYS_STUB_ARGS_FILE")
if args_file:
    with open(args_file, "w", encoding="utf-8") as f:
        json.dump(sys.argv[1:], f)

print(f"stub: 已模拟登录 {email}")
sys.exit(0)
