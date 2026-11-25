#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
agys — Antigravity (agy) 多帐号切换器

切换原理（Windows 实测验证）：
  凭据 = Windows Credential Manager 条目 `gemini:antigravity`（JSON blob）
  显示状态 = ~/.gemini/google_accounts.json（active 邮箱）
  `agys use` = 原子替换这两处 + 把当前 token 同步回其 profile（回收刷新）
  `agys as`  = use + 拉起 agy（参数透传）

仅依赖 Python 标准库。跨平台：Windows 完整实测；macOS/Linux 为最佳努力实现。
"""

import argparse
import base64
import ctypes
import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

__version__ = "0.1.0"

IS_WIN = os.name == "nt"
IS_MAC = sys.platform == "darwin"
IS_LINUX = not IS_WIN and not IS_MAC

APP = "agys"

# ---------------------------------------------------------------- 路径与环境覆盖
# 环境变量（测试/高级用途）：AGYS_HOME / AGYS_GEMINI_HOME / AGYS_CRED_TARGET /
# AGYS_CRED_USER / AGYS_AGY_BIN / AGY_PROCESS_NAMES / AGYS_DISABLE_KEYCHAIN

def user_home():
    return os.path.expanduser("~")

def _agys_home():
    return os.environ.get("AGYS_HOME") or os.path.join(user_home(), ".agy-accounts")

def _gemini_home():
    return os.environ.get("AGYS_GEMINI_HOME") or os.path.join(user_home(), ".gemini")

AGYS_HOME = _agys_home()
GEMINI_HOME = _gemini_home()
VAULT_PATH = os.path.join(AGYS_HOME, "vault.json")
PROFILES_DIR = os.path.join(AGYS_HOME, "profiles")
LOCK_PATH = os.path.join(AGYS_HOME, ".switch.lock")

CRED_TARGET = os.environ.get("AGYS_CRED_TARGET") or "gemini:antigravity"
CRED_USER = os.environ.get("AGYS_CRED_USER") or "antigravity"
GOOGLE_ACCOUNTS_PATH = os.path.join(GEMINI_HOME, "google_accounts.json")
LINUX_TOKEN_PATH = os.path.join(GEMINI_HOME, "antigravity-cli", "antigravity-oauth-token")

DEFAULT_PROCESS_NAMES = ["agy.exe", "Antigravity.exe"] if IS_WIN else ["agy", "Antigravity"]


def agy_binary():
    p = os.environ.get("AGYS_AGY_BIN")
    if p:
        return p
    cand = []
    if IS_WIN:
        la = os.environ.get("LOCALAPPDATA") or os.path.join(user_home(), "AppData", "Local")
        cand += [os.path.join(la, "agy", "bin", "agy.exe")]
    else:
        cand += [
            os.path.join(user_home(), ".gemini", "bin", "agy"),
            "/usr/bin/agy",
            "/usr/local/bin/agy",
            "/opt/Antigravity/antigravity",
        ]
    cand.append(shutil.which("agy") or "")
    for c in cand:
        if c and os.path.isfile(c):
            return c
    return None


# ---------------------------------------------------------------- 通用小工具

def now_iso():
    return datetime.datetime.now().astimezone().replace(microsecond=0).isoformat()


def atomic_write_bytes(path, data):
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".agys-tmp-", dir=d)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def atomic_write_json(path, obj):
    atomic_write_bytes(path, (json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def read_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return None


def eprint(*a):
    print(*a, file=sys.stderr)


def die(msg, code=1):
    eprint(f"{APP}: 错误：{msg}")
    sys.exit(code)


def blob_to_text(blob: bytes):
    """凭据 blob -> (text, is_b64)。能按 UTF-8 解码就存原文，否则 base64。"""
    try:
        return blob.decode("utf-8"), False
    except UnicodeDecodeError:
        return base64.b64encode(blob).decode("ascii"), True


def text_to_blob(text: str, is_b64: bool) -> bytes:
    if is_b64:
        return base64.b64decode(text)
    return text.encode("utf-8")


# ---------------------------------------------------------------- 凭据库（平台抽象）

class KeychainError(Exception):
    pass


if IS_WIN:
    import ctypes.wintypes as wt

    _advapi = ctypes.WinDLL("Advapi32", use_last_error=True)
    CRED_TYPE_GENERIC = 1
    CRED_PERSIST_LOCAL_MACHINE = 2

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

    def keychain_get():
        """读取凭据条目，返回 bytes；不存在返回 None。"""
        if os.environ.get("AGYS_DISABLE_KEYCHAIN"):
            return None
        p = ctypes.POINTER(_CREDENTIAL)()
        if not _advapi.CredReadW(CRED_TARGET, CRED_TYPE_GENERIC, 0, ctypes.byref(p)):
            err = ctypes.get_last_error()
            if err == 1168:  # ERROR_NOT_FOUND
                return None
            raise KeychainError(f"CredReadW 失败 (winerror={err})")
        try:
            c = p[0]
            return bytes(bytearray(c.CredentialBlob[:c.CredentialBlobSize]))
        finally:
            _advapi.CredFree(p)

    def keychain_set(blob: bytes):
        if os.environ.get("AGYS_DISABLE_KEYCHAIN"):
            return
        c = _CREDENTIAL()
        c.Flags = 0
        c.Type = CRED_TYPE_GENERIC
        c.TargetName = CRED_TARGET
        c.UserName = CRED_USER
        c.Persist = CRED_PERSIST_LOCAL_MACHINE
        c.CredentialBlobSize = len(blob)
        c.CredentialBlob = ctypes.cast(
            ctypes.create_string_buffer(blob, len(blob)), ctypes.POINTER(ctypes.c_byte))
        if not _advapi.CredWriteW(ctypes.byref(c), 0):
            raise KeychainError(f"CredWriteW 失败 (winerror={ctypes.get_last_error()})")

    def keychain_delete():
        if os.environ.get("AGYS_DISABLE_KEYCHAIN"):
            return
        if not _advapi.CredDeleteW(CRED_TARGET, CRED_TYPE_GENERIC, 0):
            err = ctypes.get_last_error()
            if err != 1168:  # 不存在也算成功
                raise KeychainError(f"CredDeleteW 失败 (winerror={err})")

elif IS_MAC:
    # go-keyring on macOS: service="gemini", account="antigravity"
    _SVC, _ACC = CRED_TARGET.split(":", 1) if ":" in CRED_TARGET else (CRED_TARGET, CRED_USER)

    def keychain_get():
        if os.environ.get("AGYS_DISABLE_KEYCHAIN"):
            return None
        r = subprocess.run(
            ["security", "find-generic-password", "-s", _SVC, "-a", _ACC, "-w"],
            capture_output=True)
        if r.returncode != 0:
            return None
        return r.stdout.rstrip(b"\n")

    def keychain_set(blob: bytes):
        r = subprocess.run(
            ["security", "add-generic-password", "-U", "-s", _SVC, "-a", _ACC,
             "-w", blob.decode("utf-8")],
            capture_output=True)
        if r.returncode != 0:
            raise KeychainError(f"security add 失败: {r.stderr.decode(errors='replace')}")

    def keychain_delete():
        subprocess.run(
            ["security", "delete-generic-password", "-s", _SVC, "-a", _ACC],
            capture_output=True)

else:  # Linux：优先文件式 token（~/.gemini/antigravity-cli/antigravity-oauth-token）
    def keychain_get():
        if os.environ.get("AGYS_DISABLE_KEYCHAIN"):
            return None
        try:
            with open(LINUX_TOKEN_PATH, "rb") as f:
                return f.read()
        except FileNotFoundError:
            return None
        except OSError as e:
            raise KeychainError(f"读取 {LINUX_TOKEN_PATH} 失败: {e}")

    def keychain_set(blob: bytes):
        atomic_write_bytes(LINUX_TOKEN_PATH, blob)
        try:
            os.chmod(LINUX_TOKEN_PATH, 0o600)
        except OSError:
            pass

    def keychain_delete():
        try:
            os.unlink(LINUX_TOKEN_PATH)
        except FileNotFoundError:
            pass


# ---------------------------------------------------------------- vault / profile

def load_vault():
    v = read_json_file(VAULT_PATH)
    if v is None:
        v = {"version": 1, "accounts": {}, "current": None}
    if not isinstance(v.get("accounts"), dict):
        v["accounts"] = {}
    return v


def save_vault(v):
    atomic_write_json(VAULT_PATH, v)


def profile_path(acc_id):
    return os.path.join(PROFILES_DIR, acc_id, "profile.json")


def save_profile(acc_id, blob: bytes, ga, meta):
    text, is_b64 = blob_to_text(blob)
    prof = {
        "id": acc_id,
        "email": meta.get("email") or "",
        "aliases": meta.get("aliases") or [],
        "created": meta.get("created") or now_iso(),
        "updated": now_iso(),
        "blob": text,
        "blob_b64": is_b64,
        "google_accounts": ga,
    }
    atomic_write_json(profile_path(acc_id), prof)
    return prof


def load_profile(acc_id):
    p = read_json_file(profile_path(acc_id))
    if p is None:
        raise KeyError(acc_id)
    return p


def profile_blob(prof) -> bytes:
    return text_to_blob(prof["blob"], prof.get("blob_b64", False))


def slugify(s):
    s = (s or "").strip().lower()
    out = []
    for ch in s:
        if ch.isalnum() or ch in "-_":
            out.append(ch)
        else:
            out.append("-")
    slug = "".join(out).strip("-")
    return slug or f"account-{int(time.time())}"


def email_slug(email):
    """邮箱 -> 简短 id（取 @ 前局部名，如 alice@gmail.com -> alice）。"""
    local = (email or "").split("@")[0].strip()
    return slugify(local) if local else ""


def ga_email(ga):
    try:
        e = (ga or {}).get("active")
        return e if isinstance(e, str) else None
    except Exception:
        return None


def live_blob_matches(blob: bytes):
    """返回 live blob 匹配的 profile id，无匹配返回 None。"""
    v = load_vault()
    for acc in v["accounts"]:
        try:
            prof = load_profile(acc)
        except KeyError:
            continue
        try:
            if profile_blob(prof) == blob:
                return acc
        except Exception:
            continue
    return None


def resolve(name):
    """按 id / 邮箱 / 别名解析帐号（大小写不敏感，支持唯一前缀）。"""
    v = load_vault()
    n = (name or "").strip().lower()
    exact = []
    for acc, meta in v["accounts"].items():
        keys = [acc.lower(), (meta.get("email") or "").lower()] + [
            a.lower() for a in meta.get("aliases") or []]
        if n in keys:
            exact.append(acc)
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise KeyError(f"'{name}' 匹配到多个帐号：{', '.join(exact)}，请用 id 精确指定")
    pref = [acc for acc in v["accounts"] if acc.lower().startswith(n)]
    if len(pref) == 1:
        return pref[0]
    if not v["accounts"]:
        raise KeyError("当前没有任何帐号，请先运行：agys add")
    raise KeyError(f"找不到帐号 '{name}'，现有帐号见 agys list")


# ---------------------------------------------------------------- 锁

class SwitchLock:
    """跨平台文件锁（Windows: msvcrt.locking / Unix: fcntl.flock）。"""

    def __enter__(self):
        os.makedirs(AGYS_HOME, exist_ok=True)
        self.f = open(LOCK_PATH, "a+")
        try:
            if IS_WIN:
                import msvcrt
                self.f.seek(0)
                msvcrt.locking(self.f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.f.close()
            raise RuntimeError("另一个 agys 操作正在进行（~/.agy-accounts/.switch.lock）")
        return self

    def __exit__(self, *exc):
        try:
            if IS_WIN:
                import msvcrt
                self.f.seek(0)
                msvcrt.locking(self.f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.f.fileno(), fcntl.LK_UNLCK)
        finally:
            self.f.close()
        return False


# ---------------------------------------------------------------- 进程守卫

def running_agy_processes():
    names = [s.strip() for s in
             (os.environ.get("AGYS_PROCESS_NAMES") or ",".join(DEFAULT_PROCESS_NAMES)).split(",")
             if s.strip()]
    found = []
    try:
        if IS_WIN:
            r = subprocess.run(["tasklist", "/FO", "CSV", "/NH"],
                               capture_output=True, text=True, timeout=15)
            if r.returncode == 0:
                for line in r.stdout.splitlines():
                    first = line.split('","')[0].strip('"').lower() if '","' in line else ""
                    for n in names:
                        if first and first == n.lower():
                            found.append(n)
        else:
            for n in names:
                r = subprocess.run(["pgrep", "-x", n], capture_output=True, timeout=15)
                if r.returncode == 0 and r.stdout.strip():
                    found.append(n)
    except Exception:
        return None  # 检测不可用
    return sorted(set(found))


def guard(no_guard=False):
    if no_guard:
        return
    found = running_agy_processes()
    if found is None:
        eprint(f"{APP}: 警告：无法检测 agy 进程（检测工具不可用），继续执行。")
        return
    if found:
        die("检测到正在运行的 Antigravity 进程：%s。\n"
            "后台 agy 会在 token 刷新时把旧帐号写回凭据库，导致切换被静默回退。\n"
            "请先退出这些进程，或使用 --no-guard 强制切换（风险自负）。"
            % ", ".join(found))


# ---------------------------------------------------------------- 核心切换逻辑

def snapshot_live_as(acc_id, ga, v, notice_prefix=""):
    blob = keychain_get()
    if blob is None:
        return None
    text, is_b64 = blob_to_text(blob)
    existing = None
    for acc in v["accounts"]:
        try:
            p = load_profile(acc)
            if p.get("blob") == text and p.get("blob_b64", False) == is_b64:
                existing = acc
                break
        except KeyError:
            continue
    if existing:
        # token 被后台刷新过 -> 回收进已有 profile
        meta = dict(v["accounts"][existing])
        save_profile(existing, blob, ga, meta)
        return existing
    # 未纳管的新登录：若同名 id 已存在（如手动重新登录），保留其原别名等元数据
    if acc_id in v["accounts"]:
        meta = dict(v["accounts"][acc_id])
    else:
        meta = {"email": ga_email(ga) or "", "aliases": []}
    save_profile(acc_id, blob, ga, meta)
    v["accounts"][acc_id] = {"id": acc_id, "email": meta["email"], "aliases": [],
                             "created": now_iso()}
    if notice_prefix:
        print(f"{APP}: {notice_prefix}已把当前登录保存为帐号 '{acc_id}'"
              f"（{meta['email'] or '邮箱未知'}）")
    return acc_id


def read_live_ga():
    return read_json_file(GOOGLE_ACCOUNTS_PATH)


def write_live_ga(ga):
    if ga is not None:
        atomic_write_json(GOOGLE_ACCOUNTS_PATH, ga)


def switch_to(acc_id, v, no_guard=False):
    """切换到指定帐号。调用方需持有 SwitchLock。"""
    guard(no_guard)
    ga = read_live_ga()
    live = keychain_get()
    if live is not None:
        email = ga_email(ga) or ""
        cur = v.get("current")
        cur_email = ""
        if cur and cur in v["accounts"]:
            cur_email = (v["accounts"][cur].get("email") or "")
        exact = live_blob_matches(live)
        if exact is not None:
            # 与某个已存帐号的 token 完全一致（或刚被刷新后已同步过）-> 回收刷新
            meta = dict(v["accounts"][exact])
            save_profile(exact, live, ga, meta)
            if v.get("current") != exact:
                v["current"] = exact
                save_vault(v)
        elif cur and email and cur_email and email.lower() == cur_email.lower():
            # token 被 agy 轮换/刷新过（内容变了但仍是当前帐号）-> 回收回当前帐号
            meta = dict(v["accounts"][cur])
            save_profile(cur, live, ga, meta)
        else:
            # live 凭据未纳入管理（比如手动重新登录了新帐号）-> 自动收录，防止丢失
            adopt_id = email_slug(email) or f"untracked-{int(time.time())}"
            rid = snapshot_live_as(adopt_id, ga, v, notice_prefix="检测到未纳管的当前登录，")
            if rid:
                v["current"] = rid
                save_vault(v)

    prof = load_profile(acc_id)
    blob = profile_blob(prof)
    prev_blob = keychain_get()
    prev_ga = read_live_ga()
    try:
        keychain_set(blob)
        write_live_ga(prof.get("google_accounts"))
        v["current"] = acc_id
        save_vault(v)
    except Exception:
        # 回滚
        try:
            if prev_blob is None:
                keychain_delete()
            else:
                keychain_set(prev_blob)
            if prev_ga is not None:
                write_live_ga(prev_ga)
        except Exception as re_:
            eprint(f"{APP}: 严重：回滚失败：{re_}（当前凭据可能处于不一致状态，"
                   f"请运行 agys doctor 检查）")
        raise
    email = prof.get("email") or "?"
    print(f"{APP}: 已切换到 '{acc_id}'（{email}）")


# ---------------------------------------------------------------- 命令实现

def cmd_add(args):
    with SwitchLock():
        guard(getattr(args, "no_guard", False))
        v = load_vault()
        ga = read_live_ga()
        live = keychain_get()
        backed_up = None
        if live is not None:
            # 当前登录必须先保存，否则新登录会覆盖
            email = ga_email(ga) or ""
            existing = live_blob_matches(live)
            cur = v.get("current")
            cur_email = ""
            if cur and cur in v["accounts"]:
                cur_email = (v["accounts"][cur].get("email") or "")
            if existing is None and cur and email and cur_email \
                    and email.lower() == cur_email.lower():
                existing = cur  # token 被刷新过，但仍是当前帐号
            if existing is not None:
                rid = snapshot_live_as(existing, ga, v)
                save_vault(v)
                backed_up = rid
                print(f"{APP}: 已把当前登录（'{rid}'）的最新 token 存回库中。")
            else:
                rid = snapshot_live_as(email_slug(email) or f"untracked-{int(time.time())}",
                                       ga, v, notice_prefix="首次使用，")
                save_vault(v)
                backed_up = rid
        # 走到登录流程前先登出
        keychain_delete()
        binp = agy_binary()
        if not binp:
            if backed_up:
                die("找不到 agy 可执行文件（已保留原帐号凭据，未做切换）")
            die("找不到 agy 可执行文件")
        print(f"{APP}: 即将启动 agy 登录流程，请在浏览器中完成 Google 登录，"
              f"登录完成后退出 agy（Ctrl+C 或 /quit）。")
        try:
            subprocess.call([binp])
        except KeyboardInterrupt:
            pass
        new_blob = keychain_get()
        if new_blob is None:
            # 没登录成功 -> 回滚恢复原帐号
            if live is not None:
                keychain_set(live)
            die("未检测到新登录（凭据条目仍为空），已恢复原帐号凭据。")
        if live is not None and new_blob == live:
            # 登录了同一个帐号 -> 更新该 profile 后返回
            if backed_up:
                snapshot_live_as(backed_up, read_live_ga(), v)
                save_vault(v)
            print(f"{APP}: 检测到登录的还是同一帐号，已刷新其 token。")
            return
        new_ga = read_live_ga()
        email = ga_email(new_ga) or ""
        base = args.name or email_slug(email) or f"account-{int(time.time())}"
        acc_id = slugify(base)
        if acc_id in v["accounts"]:
            die(f"帐号 id '{acc_id}' 已存在，换一个名字（agys add <名字>）或先 remove。")
        save_profile(acc_id, new_blob, new_ga, {"email": email, "aliases": []})
        v["accounts"][acc_id] = {"id": acc_id, "email": email, "aliases": [],
                                 "created": now_iso()}
        v["current"] = acc_id
        save_vault(v)
        print(f"{APP}: 已添加并切换到新帐号 '{acc_id}'（{email or '邮箱未知'}）。")


def cmd_list(args):
    v = load_vault()
    if not v["accounts"]:
        print("还没有任何帐号。用 agys add 添加第一个（会自动把你当前登录的帐号也保存进来）。")
        return
    cur = v.get("current")
    email_len = max([len(m.get("email") or "") for m in v["accounts"].values()] + [5])
    print(f"{'*':<2} {'ID':<24} {'EMAIL':<{email_len}} ALIASES")
    for acc, m in sorted(v["accounts"].items()):
        mark = "*" if acc == cur else " "
        aliases = ",".join(m.get("aliases") or [])
        print(f"{mark:<2} {acc:<24} {(m.get('email') or '-'):<{email_len}} {aliases}")
    print(f"\n共 {len(v['accounts'])} 个帐号；* = 当前帐号。")


def cmd_current(args):
    v = load_vault()
    cur = v.get("current")
    live = keychain_get()
    ga = read_live_ga()
    live_email = ga_email(ga) or "-"
    if live is None:
        live_state = "无凭据（未登录）"
    else:
        m = live_blob_matches(live)
        live_state = f"匹配帐号 '{m}'" if m else "未纳管（下次 use/add 会自动收录）"
    if cur and cur in v["accounts"]:
        email = v["accounts"][cur].get("email") or "-"
        print(f"当前帐号（vault）: {cur} ({email})")
    else:
        print("当前帐号（vault）: 无")
    print(f"活跃凭据: {live_state}")
    print(f"活跃邮箱（google_accounts.json）: {live_email}")


def cmd_use(args):
    try:
        acc_id = resolve(args.name)
    except KeyError as e:
        die(str(e))
    with SwitchLock():
        v = load_vault()
        try:
            switch_to(acc_id, v, no_guard=args.no_guard)
        except KeyError:
            die(f"帐号 '{args.name}' 的 profile 数据缺失，请 agys doctor 检查。")


def cmd_as(args):
    if not args.args_cmd:
        die("用法：agys as <帐号> [--] [agy 的参数...]")
    agy_args = args.args_cmd
    if agy_args and agy_args[0] == "--":
        agy_args = agy_args[1:]
    try:
        acc_id = resolve(args.name)
    except KeyError as e:
        die(str(e))
    v = load_vault()
    cur = v.get("current")
    need_switch = True
    if cur == acc_id:
        live = keychain_get()
        if live is not None:
            try:
                need_switch = profile_blob(load_profile(acc_id)) != live
            except KeyError:
                pass
    if need_switch:
        with SwitchLock():
            v = load_vault()
            switch_to(acc_id, v, no_guard=args.no_guard)
    else:
        print(f"{APP}: '{acc_id}' 已是当前帐号，直接启动 agy。")
    binp = agy_binary()
    if not binp:
        die("找不到 agy 可执行文件（可用 AGYS_AGY_BIN 环境变量指定）。")
    rc = subprocess.call([binp] + agy_args)
    sys.exit(rc)


def cmd_remove(args):
    try:
        acc_id = resolve(args.name)
    except KeyError as e:
        die(str(e))
    with SwitchLock():
        v = load_vault()
        if acc_id not in v["accounts"]:
            die(f"帐号 '{acc_id}' 不存在。")
        was_current = v.get("current") == acc_id
        v["accounts"].pop(acc_id)
        if was_current:
            v["current"] = None
        save_vault(v)
        pdir = os.path.join(PROFILES_DIR, acc_id)
        if os.path.isdir(pdir):
            shutil.rmtree(pdir)
        if was_current:
            # 删的是当前活跃帐号 -> 同时清掉活跃凭据，避免下次被自动复活
            try:
                keychain_delete()
                print(f"{APP}: 已删除当前帐号 '{acc_id}' 并清除活跃凭据（相当于登出）。")
            except KeychainError as e:
                print(f"{APP}: 已删除帐号记录，但清除凭据失败：{e}")
        else:
            print(f"{APP}: 已删除帐号 '{acc_id}'。")


def cmd_export(args):
    v = load_vault()
    if not v["accounts"]:
        die("没有任何帐号可导出。")
    path = args.path or os.path.join(os.getcwd(),
                                     f"agys-export-{datetime.date.today().isoformat()}.json")
    accounts = []
    for acc in sorted(v["accounts"]):
        try:
            prof = load_profile(acc)
        except KeyError:
            eprint(f"{APP}: 警告：帐号 '{acc}' 的 profile 数据缺失，跳过。")
            continue
        accounts.append({
            "id": prof["id"], "email": prof.get("email") or "",
            "aliases": prof.get("aliases") or [],
            "created": prof.get("created") or "",
            "blob": prof["blob"], "blob_b64": prof.get("blob_b64", False),
            "google_accounts": prof.get("google_accounts"),
        })
    out = {
        "format": "agys-export", "version": 1, "exported_at": now_iso(),
        "note": "迁移用途：refresh token 会被轮换。导入新机器后，请在源机器上删除本帐号"
                "（agys remove）或停止使用，避免两台机器互相踢掉登录。",
        "accounts": accounts,
    }
    atomic_write_json(path, out)
    print(f"{APP}: 已导出 {len(accounts)} 个帐号到 {path}")
    print(f"{APP}: ⚠ 文件内含可登录凭据（明文），请妥善保管、迁移完成后删除。")


def cmd_import(args):
    path = args.path
    if not os.path.isfile(path):
        die(f"文件不存在：{path}")
    data = read_json_file(path)
    if not isinstance(data, dict) or data.get("format") != "agys-export":
        die("不是有效的 agys 导出文件（缺少 format: agys-export 标记）。")
    accs = data.get("accounts")
    if not isinstance(accs, list) or not accs:
        die("导出文件中没有帐号数据。")
    with SwitchLock():
        v = load_vault()
        added, updated = [], []
        for a in accs:
            if not a.get("blob") or not a.get("id"):
                continue
            acc_id = slugify(a["id"])
            existed = acc_id in v["accounts"]
            meta = {"email": a.get("email") or "", "aliases": a.get("aliases") or [],
                    "created": a.get("created") or now_iso()}
            save_profile(acc_id, text_to_blob(a["blob"], a.get("blob_b64", False)),
                         a.get("google_accounts"), meta)
            v["accounts"][acc_id] = {"id": acc_id, **meta}
            (updated if existed else added).append(acc_id)
        save_vault(v)
        if added:
            print(f"{APP}: 新导入 {len(added)} 个帐号：{', '.join(added)}")
        if updated:
            print(f"{APP}: 更新 {len(updated)} 个已有帐号：{', '.join(updated)}")
        print(f"{APP}: 导入完成。用 agys use <id> 切换，agys list 查看。"
              f"（导入不会自动切换当前帐号）")


def cmd_doctor(args):
    print(f"{APP} v{__version__} 诊断")
    print(f"  平台: {sys.platform}  Python: {sys.version.split()[0]}")
    print(f"  agys 目录: {AGYS_HOME}")
    print(f"  gemini 目录: {GEMINI_HOME}")

    binp = agy_binary()
    print(f"  agy 可执行文件: {binp or '未找到!'}")
    if not binp:
        print("    -> 请安装 Antigravity CLI，或设置 AGYS_AGY_BIN 环境变量。")

    print(f"  凭据条目标标: {CRED_TARGET} (user={CRED_USER}, "
          f"{'Windows Credential Manager' if IS_WIN else 'macOS Keychain' if IS_MAC else '文件式 ' + LINUX_TOKEN_PATH})")
    try:
        live = keychain_get()
    except KeychainError as e:
        live = None
        print(f"    -> 读取失败: {e}")
    if live is None:
        print("    -> 当前无活跃凭据（未登录）")
    else:
        m = live_blob_matches(live)
        print(f"    -> 有活跃凭据，{('匹配帐号 ' + m) if m else '未纳管'}，blob {len(live)} 字节")

    ga = read_live_ga()
    print(f"  google_accounts.json: "
          f"{('active=' + str(ga_email(ga))) if ga is not None else '不存在（未登录过或被清理）'}")

    v = load_vault()
    print(f"  vault: {len(v['accounts'])} 个帐号，当前 = {v.get('current') or '无'}")
    for acc in sorted(v["accounts"]):
        try:
            prof = load_profile(acc)
            blob = profile_blob(prof)
            ok = blob is not None and len(blob) > 0
            print(f"    [{'ok' if ok else '坏'}] {acc} ({prof.get('email') or '-'}) "
                  f"blob {len(blob) if ok else 0} 字节")
        except (KeyError, Exception) as e:
            print(f"    [坏] {acc}: {e}")

    found = running_agy_processes()
    if found is None:
        print("  运行中 agy 进程: 无法检测")
    elif found:
        print(f"  运行中 agy 进程: {', '.join(found)}（切换前需退出）")
    else:
        print("  运行中 agy 进程: 无")

    if not IS_WIN:
        print("  注意: macOS/Linux 的凭据读写为最佳努力实现，未经实机验证，"
              "如异常请提 issue 附上 agys doctor 输出。")
    print(f"  安全提示: {PROFILES_DIR} 内含明文登录凭据，请勿放入同步盘/共享目录。")


# ---------------------------------------------------------------- 入口

def build_parser():
    p = argparse.ArgumentParser(prog=APP, description="Antigravity (agy) 多帐号切换器")
    p.add_argument("--version", action="version", version=f"{APP} {__version__}")
    sub = p.add_subparsers(dest="cmd")

    sp = sub.add_parser("add", help="添加帐号（先保存当前登录，再走 agy 登录流程，完成后直接生效）")
    sp.add_argument("name", nargs="?", help="帐号名（缺省用登录邮箱）")
    sp.add_argument("--no-guard", action="store_true", help="跳过运行中进程检测（风险自负）")
    sp.set_defaults(func=cmd_add)

    sp = sub.add_parser("list", help="列出所有帐号")
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("current", help="查看当前帐号与活跃凭据状态")
    sp.set_defaults(func=cmd_current)

    sp = sub.add_parser("use", help="切换到指定帐号（id/邮箱/别名）")
    sp.add_argument("name")
    sp.add_argument("--no-guard", action="store_true", help="跳过运行中进程检测（风险自负）")
    sp.set_defaults(func=cmd_use)

    sp = sub.add_parser("as", help="切换到指定帐号并以该帐号启动 agy（后续参数透传给 agy）")
    sp.add_argument("name")
    sp.add_argument("args_cmd", nargs=argparse.REMAINDER, help="透传给 agy 的参数")
    sp.add_argument("--no-guard", action="store_true", help="跳过运行中进程检测（风险自负）")
    sp.set_defaults(func=cmd_as)

    sp = sub.add_parser("remove", help="删除帐号（删除当前帐号会同时登出）")
    sp.add_argument("name")
    sp.set_defaults(func=cmd_remove)

    sp = sub.add_parser("export", help="导出所有帐号（迁移用途，明文凭据）")
    sp.add_argument("path", nargs="?", help="输出文件路径（缺省当前目录 agys-export-<日期>.json）")
    sp.set_defaults(func=cmd_export)

    sp = sub.add_parser("import", help="从导出文件导入帐号（不自动切换）")
    sp.add_argument("path")
    sp.set_defaults(func=cmd_import)

    sp = sub.add_parser("doctor", help="环境自检")
    sp.set_defaults(func=cmd_doctor)
    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        sys.exit(0)
    try:
        args.func(args)
    except KeychainError as e:
        die(str(e))
    except RuntimeError as e:
        die(str(e))
    except KeyboardInterrupt:
        eprint(f"\n{APP}: 已取消。")
        sys.exit(130)


if __name__ == "__main__":
    main()
