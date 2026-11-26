"""路径与环境配置。

所有路径都通过 paths() 动态解析（每次读取环境变量），便于测试隔离，
不缓存任何全局状态。
"""
from __future__ import annotations

import os
import shlex
import shutil
import sys
from dataclasses import dataclass

IS_WIN = os.name == "nt"
IS_MAC = sys.platform == "darwin"
IS_LINUX = not IS_WIN and not IS_MAC

# agy 在系统凭据库里的默认条目名。布局自动发现以它为基线做候选枚举。
DEFAULT_CRED_TARGET = "gemini:antigravity"


@dataclass(frozen=True)
class Paths:
    home: str
    gemini_home: str
    install_dir: str
    vault: str
    config_file: str
    profiles: str
    lock: str
    pending: str
    audit: str
    exports: str
    key_file: str
    memory_file: str
    reopen: str
    ga: str
    linux_token: str
    cred_target: str
    cred_user: str
    no_encrypt: bool
    backend: str
    process_names: str


def _env(name, default):
    v = os.environ.get(name)
    return default if v is None else v


# layout 自动适配写入的路径覆盖（进程级，不写进环境变量，避免污染子进程）
_OVERRIDES: dict = {}


def set_overrides(d=None):
    _OVERRIDES.clear()
    if d:
        for key in ("cred_target", "ga", "linux_token"):
            value = d.get(key)
            if value:
                _OVERRIDES[key] = value


def get_overrides():
    return dict(_OVERRIDES)


def paths() -> Paths:
    user = os.path.expanduser("~")
    home = _env("AGYS_HOME", os.path.join(user, ".agy-accounts"))
    gemini = _env("AGYS_GEMINI_HOME", os.path.join(user, ".gemini"))
    install = _env("AGYS_INSTALL_DIR", os.path.join(user, ".agys"))
    return Paths(
        home=home,
        gemini_home=gemini,
        install_dir=install,
        vault=os.path.join(home, "vault.json"),
        config_file=os.path.join(home, "config.json"),
        profiles=os.path.join(home, "profiles"),
        lock=os.path.join(home, ".switch.lock"),
        pending=os.path.join(home, "pending.json"),
        audit=os.path.join(home, "audit.jsonl"),
        exports=_env("AGYS_EXPORTS_DIR", os.path.join(home, "exports")),
        key_file=os.path.join(home, ".vault.key"),
        memory_file=_env("AGYS_MEMORY_FILE", os.path.join(home, "memory_credential.json")),
        reopen=os.path.join(home, "reopen.json"),
        ga=_OVERRIDES.get("ga") or os.path.join(gemini, "google_accounts.json"),
        linux_token=(_OVERRIDES.get("linux_token")
                     or os.path.join(gemini, "antigravity-cli", "antigravity-oauth-token")),
        cred_target=(_env("AGYS_CRED_TARGET", None)
                     or _OVERRIDES.get("cred_target") or DEFAULT_CRED_TARGET),
        cred_user=_env("AGYS_CRED_USER", "antigravity"),
        no_encrypt=os.environ.get("AGYS_NO_ENCRYPT") == "1",
        backend=_env("AGYS_BACKEND", "auto"),
        process_names=_env(
            "AGYS_PROCESS_NAMES",
            "agy.exe,Antigravity.exe" if IS_WIN else "agy,Antigravity",
        ),
    )


def agy_binary() -> str:
    """定位 agy 可执行文件；找不到返回空串。"""
    override = os.environ.get("AGYS_AGY_BIN")
    if override:
        return override
    candidates = []
    if IS_WIN:
        la = os.environ.get("LOCALAPPDATA") or os.path.join(
            os.path.expanduser("~"), "AppData", "Local")
        candidates.append(os.path.join(la, "agy", "bin", "agy.exe"))
    else:
        candidates += [
            os.path.join(os.path.expanduser("~"), ".local", "bin", "agy"),
            os.path.join(os.path.expanduser("~"), ".gemini", "bin", "agy"),
            "/usr/bin/agy",
            "/usr/local/bin/agy",
            "/opt/Antigravity/antigravity",
        ]
    candidates.append(shutil.which("agy") or "")
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return ""


def agy_argv(extra=None):
    """把 AGYS_AGY_BIN 展开成 argv。允许用 'python3 /path/to/stub.py'
    这样的命令串做测试替身，也支持带空格的路径。"""
    b = agy_binary()
    if not b:
        return []
    parts = shlex.split(b, posix=(os.name != "nt"))
    return [x.strip('"').strip("'") for x in parts] + list(extra or [])
