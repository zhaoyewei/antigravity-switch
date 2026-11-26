"""存储布局探测。

agy 升级换存储位置时，写死路径会静默失效——这里生成结构指纹，
切换前比对，不一致就拒绝切换（而不是假装成功）。
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys

from . import identity
from .config import IS_WIN, agy_argv, agy_binary, paths
from .vault import load_vault, save_vault


def agy_version() -> str:
    argv = agy_argv(["--version"])
    if not argv:
        return "unknown"
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=15)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip().splitlines()[0].strip()
    except Exception:
        pass
    return "unknown"


def ide_state_path():
    if IS_WIN:
        base = os.environ.get("APPDATA") or os.path.join(
            os.path.expanduser("~"), "AppData", "Roaming")
        return os.path.join(base, "Antigravity IDE", "User", "globalStorage", "state.vscdb")
    import sys
    if sys.platform == "darwin":
        return os.path.join(os.path.expanduser("~"), "Library", "Application Support",
                            "Antigravity IDE", "User", "globalStorage", "state.vscdb")
    return os.path.join(os.path.expanduser("~"), ".config", "Antigravity IDE",
                        "User", "globalStorage", "state.vscdb")


def probe(store) -> dict:
    p = paths()
    platform = "windows" if IS_WIN else "macos" if sys.platform == "darwin" else "linux"
    fields = {
        "agy_version": agy_version(),
        "platform": platform,
        "backend": store.name,
        "cred_target": p.cred_target,
        "ga_path": p.ga,
        "token_path": p.linux_token,
        "ide_state_path": ide_state_path(),
    }
    fp = hashlib.sha256(json.dumps(fields, sort_keys=True, ensure_ascii=False,
                                   separators=(",", ":")).encode("utf-8")).hexdigest()[:16]
    return {
        **fields,
        "fingerprint": fp,
        "has_credential": store.get() is not None if hasattr(store, "get") else False,
        "ga_exists": os.path.isfile(p.ga),
        "token_exists": os.path.isfile(p.linux_token),
        "ide_state_exists": os.path.isfile(ide_state_path()),
        "agy_binary": agy_binary(),
    }


def verify(vault, store, allow_change=False):
    """返回 (ok, message)。首次运行自动记录布局。"""
    cur = probe(store)
    cached = vault.get("layout")
    if not cached:
        vault["layout"] = cur
        save_vault(vault)
        return True, f"已记录存储布局指纹 {cur['fingerprint']}（agy {cur['agy_version']}）"
    if cached.get("fingerprint") == cur["fingerprint"]:
        return True, ""
    diff = []
    for k in ("agy_version", "backend", "cred_target", "ga_path", "token_path"):
        if cached.get(k) != cur.get(k):
            diff.append(f"{k}: {cached.get(k)!r} -> {cur.get(k)!r}")
    if allow_change:
        vault["layout"] = cur
        save_vault(vault)
        return True, ("存储布局已变化并接受更新：" + "; ".join(diff))
    return False, (
        "检测到 agy 存储布局变化，已拒绝切换以防写到失效位置：\n  "
        + ("\n  ".join(diff) or "指纹变化")
        + "\n请先运行 agys layout 查看现状，确认无误后加 --allow-layout-change 重试。")


def live_identity(store, ga):
    blob = store.get()
    if blob is None:
        return None
    return identity.extract(blob, ga)
