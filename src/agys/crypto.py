"""本地凭据加密与文件权限。

Windows 用 DPAPI（绑定当前 OS 用户）；macOS/Linux 用标准库构造的
SHAKE256 流密码 + HMAC-SHA256 认证加密，密钥保存在 0600 文件中。
export 文件始终是明文（用户明确要求），这里只加密本地 vault。

AGYS_NO_ENCRYPT=1 可关闭加密（迁移/调试用），unseal 兼容旧明文格式。
"""
from __future__ import annotations

import ctypes
import hashlib
import hmac
import os
import tempfile

from .config import IS_WIN, paths

MAGIC_PLAIN = b"AGYSP1"
MAGIC_SEALED = b"AGYSS1"
MAGIC_DPAPI = b"AGYSD1"
ENTROPY = b"agys-vault-v2"


class CryptoError(Exception):
    pass


# ---------------------------------------------------------------- 文件权限

def secure_dir(path: str):
    os.makedirs(path, exist_ok=True)
    if IS_WIN:
        # 目录级 ACL 一次设置，文件继承，避免每次写文件都启动进程
        _win_acl(path)
    else:
        try:
            os.chmod(path, 0o700)
        except OSError:
            pass


def secure_write(path: str, data: bytes):
    """原子写 + 尽量收紧权限。"""
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".agys-tmp-", dir=d)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if IS_WIN:
            pass  # 由 home 目录的 ACL 继承提供保护
        else:
            os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _win_acl(path: str):
    """用 Windows API 设置目录 DACL（不启动外部程序）。

    仅授予 SYSTEM / Administrators / 当前用户完全控制，并保护 DACL 不继承。
    失败时静默降级，doctor 会提示用户手动收紧。
    """
    if not IS_WIN:
        return
    try:
        adv = ctypes.WinDLL("Advapi32", use_last_error=True)
        user = os.environ.get("USERNAME") or ""
        if not user:
            return
        sid = ctypes.create_string_buffer(256)
        cb = ctypes.c_ulong(ctypes.sizeof(sid))
        dom = ctypes.create_unicode_buffer(256)
        cbdom = ctypes.c_ulong(ctypes.sizeof(dom))
        snu = ctypes.c_ulong()
        if not adv.LookupAccountNameW(None, user, sid, ctypes.byref(cb),
                                      dom, ctypes.byref(cbdom), ctypes.byref(snu)):
            return
        psid = ctypes.c_void_p()
        if not adv.ConvertSidToStringSidW(sid, ctypes.byref(psid)):
            return
        try:
            sid_str = ctypes.wstring_at(psid.value)
            sddl = ("O:%sD:PAI(A;;FA;;;SY)(A;;FA;;;BA)(A;;FA;;;%s)"
                    % (sid_str, sid_str))
            sd = ctypes.c_void_p()
            if not adv.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                    sddl, 1, ctypes.byref(sd), None):
                return
            try:
                # DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION
                adv.SetFileSecurityW(path, 0x10000004, sd)
            finally:
                ctypes.windll.kernel32.LocalFree(sd)
        finally:
            ctypes.windll.kernel32.LocalFree(psid)
    except Exception:
        pass


# ---------------------------------------------------------------- 密钥文件

def _load_or_create_key(key_file: str) -> bytes:
    try:
        with open(key_file, "rb") as f:
            key = f.read()
        if len(key) >= 32:
            return key[:32]
    except FileNotFoundError:
        pass
    key = os.urandom(32)
    secure_write(key_file, key)
    return key


# ---------------------------------------------------------------- DPAPI

class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_ulong), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob(data: bytes):
    buf = ctypes.create_string_buffer(data, len(data) or 1)
    return _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte))), buf


def _dpapi_protect(data: bytes) -> bytes:
    if not IS_WIN:
        raise CryptoError("DPAPI 仅适用于 Windows")
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    inp, keep1 = _blob(data)
    ent, keep2 = _blob(ENTROPY)
    out = _DATA_BLOB()
    ok = crypt32.CryptProtectData(
        ctypes.byref(inp), None, ctypes.byref(ent), None, None, 0, ctypes.byref(out))
    if not ok:
        raise CryptoError(f"CryptProtectData 失败 (winerror={ctypes.get_last_error()})")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


def _dpapi_unprotect(data: bytes) -> bytes:
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    inp, keep1 = _blob(data)
    ent, keep2 = _blob(ENTROPY)
    out = _DATA_BLOB()
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(inp), None, ctypes.byref(ent), None, None, 0, ctypes.byref(out))
    if not ok:
        raise CryptoError(
            f"CryptUnprotectData 失败 (winerror={ctypes.get_last_error()})；"
            "vault 可能由另一个 Windows 用户创建，无法解密")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


# ---------------------------------------------------------------- SHAKE256 + HMAC

def _shake_seal(data: bytes, key_file: str) -> bytes:
    key = _load_or_create_key(key_file)
    nonce = os.urandom(16)
    ks = hashlib.shake_256(key + nonce).digest(len(data))
    ct = bytes(a ^ b for a, b in zip(data, ks))
    mac = hmac.new(key, nonce + ct, hashlib.sha256).digest()
    return nonce + mac + ct


def _shake_unseal(blob: bytes, key_file: str) -> bytes:
    if len(blob) < 48:
        raise CryptoError("密文长度不足")
    key = _load_or_create_key(key_file)
    nonce, mac, ct = blob[:16], blob[16:48], blob[48:]
    expected = hmac.new(key, nonce + ct, hashlib.sha256).digest()
    if not hmac.compare_digest(mac, expected):
        raise CryptoError("MAC 校验失败：vault 文件被篡改或密钥不匹配")
    ks = hashlib.shake_256(key + nonce).digest(len(ct))
    return bytes(a ^ b for a, b in zip(ct, ks))


# ---------------------------------------------------------------- 对外接口

def seal(data: bytes) -> bytes:
    p = paths()
    if p.no_encrypt:
        return MAGIC_PLAIN + data
    if IS_WIN:
        return MAGIC_DPAPI + _dpapi_protect(data)
    return MAGIC_SEALED + _shake_seal(data, p.key_file)


def unseal(blob: bytes) -> bytes:
    p = paths()
    if blob.startswith(MAGIC_PLAIN):
        return blob[len(MAGIC_PLAIN):]
    if blob.startswith(MAGIC_DPAPI):
        return _dpapi_unprotect(blob[len(MAGIC_DPAPI):])
    if blob.startswith(MAGIC_SEALED):
        return _shake_unseal(blob[len(MAGIC_SEALED):], p.key_file)
    raise CryptoError("未知的 vault 加密格式（可能损坏或来自不兼容版本）")
