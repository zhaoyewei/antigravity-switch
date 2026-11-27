"""从「agy 用户文件夹」导入已有登录态（不需要再走一次浏览器登录）。

典型来源：把某个帐号用过的 agy 数据目录整份拷出来，改名成一个文件夹，例如

    ~/.agy-account_userA/
        google_accounts.json                     ← 只有 active 邮箱（可选）
        oauth_creds.json                         ← Gemini CLI 的凭据文件
        antigravity-cli/antigravity-oauth-token  ← 纯 Linux 下的令牌文件
        agy-credential.json                      ← agy 原生凭据 blob（可选）

支持三种凭据形态，按可信度排序（不依赖文件名，靠内容识别）：

1. **agy 原生 blob**：`{"auth_method":"oauth","token":{access_token, refresh_token,
   token_type, expiry}}` —— Windows / macOS 凭据库里的形态，也是 Linux 令牌文件的内容；
2. **Gemini CLI 的 oauth_creds.json**：顶层 `access_token` / `refresh_token` /
   `expiry_date`，按字段映射成 agy blob。实测同一登录态下两者的 access_token 与
   refresh_token 完全一致，只有过期时间的写法不同（epoch 毫秒 vs ISO 字符串）；
3. **agys 自己的导出文件**：识别出来后不在这里处理，提示改用文件导入。

本模块只读：不改源目录、不碰当前凭据，也不打印任何 token 值。
"""
from __future__ import annotations

import datetime
import json
import os
from dataclasses import dataclass, field

from . import identity

# 扫描时直接跳过的目录：体积大、不可能放凭据
SKIP_DIRS = {
    ".git", ".svn", ".hg", "__pycache__", "node_modules", "site-packages",
    ".venv", "venv", "cache", "caches", "logs", "log", "tmp", "temp",
    "crashes", "conversations", "brain", "knowledge", "builtin", "updater",
    "extensions", "bin",
}
MAX_DEPTH = 3            # agy / gemini 的凭据最多埋到 antigravity-cli/xxx 这一层
MAX_FILES = 600          # 防止误指向一个巨大的目录时卡住
MAX_BYTES = 1 << 20      # 凭据文件都很小，超过 1 MiB 的一定不是

GA_NAME = "google_accounts.json"
# 已知文件名只用于「同样可信时优先选谁」，识别本身靠内容
KNOWN_NAMES = (
    "antigravity-oauth-token", "oauth_creds.json", "agy-credential.json",
    "antigravity-credential.json", "credentials.json", "token.json",
)

KIND_LABELS = {
    "agy-blob": "agy 原生凭据",
    "oauth-creds": "Gemini CLI oauth_creds.json",
    "agys-export": "agys 导出文件",
    "agys-profile": "agys 加密 profile",
}


class FolderImportError(Exception):
    """文件夹里没有可用的登录态（附带「该放什么」的说明）。"""


@dataclass
class Candidate:
    path: str
    kind: str
    data: dict
    depth: int

    @property
    def priority(self):
        kind_rank = {"agy-blob": 0, "oauth-creds": 1}.get(self.kind, 9)
        known = 0 if os.path.basename(self.path).lower() in KNOWN_NAMES else 1
        return (kind_rank, known, self.depth, self.path.lower())


@dataclass
class FolderAccount:
    """一次成功扫描的结果。`blob` 已经是 agy 能直接用的凭据形态。"""

    blob: bytes
    kind: str
    source: str
    identity: str
    email: str
    ga: dict | None
    others: list = field(default_factory=list)
    files_seen: int = 0

    @property
    def kind_label(self) -> str:
        return KIND_LABELS.get(self.kind, self.kind)


# ---------------------------------------------------------------- 格式化工具

def kind_label(kind: str) -> str:
    return KIND_LABELS.get(kind, kind)


def _depth_of(root: str, dirpath: str) -> int:
    rel = os.path.relpath(dirpath, root)
    if rel in (".", ""):
        return 0
    return rel.count(os.sep) + 1


def _read_json(path: str):
    try:
        if os.path.getsize(path) > MAX_BYTES:
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError, UnicodeDecodeError):
        return None


def _classify_file(path: str):
    """返回 (kind, data)；不是凭据文件就返回 (None, None)。"""
    data = _read_json(path)
    if not isinstance(data, dict):
        return None, None
    if data.get("format") == "agys-export":
        return "agys-export", data
    if data.get("sealed_blob"):
        return "agys-profile", data
    token = data.get("token")
    if isinstance(token, dict) and (token.get("refresh_token") or token.get("access_token")):
        return "agy-blob", data
    if isinstance(data.get("refresh_token"), str) and data["refresh_token"]:
        return "oauth-creds", data
    return None, None


def _valid_ga(data) -> bool:
    return (isinstance(data, dict) and isinstance(data.get("active"), str)
            and bool(data["active"].strip()))


def _expiry_iso(data: dict) -> str:
    """把各种过期时间写法统一成 agy 的 `2026-09-26T15:22:45.000000Z`。"""
    for key in ("expiry", "expires_at", "expiry_date"):
        raw = data.get(key)
        if raw in (None, ""):
            continue
        if isinstance(raw, str) and not raw.strip().replace(".", "").isdigit():
            return raw.strip()
        try:
            ts = float(raw)
        except (TypeError, ValueError):
            continue
        if ts > 1e11:                 # 毫秒
            ts /= 1000.0
        try:
            dt = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc)
        except (OverflowError, OSError, ValueError):
            continue
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"
    return ""


def to_agy_blob(kind: str, data: dict) -> bytes:
    """把候选数据转成 agy 凭据库里的那种 blob（字节）。"""
    if kind == "agy-blob":
        return json.dumps(data, ensure_ascii=False).encode("utf-8")
    token = {}
    if isinstance(data.get("access_token"), str) and data["access_token"]:
        token["access_token"] = data["access_token"]
    token["token_type"] = (data.get("token_type") or "Bearer") \
        if isinstance(data.get("token_type"), str) else "Bearer"
    if isinstance(data.get("refresh_token"), str) and data["refresh_token"]:
        token["refresh_token"] = data["refresh_token"]
    expiry = _expiry_iso(data)
    if expiry:
        token["expiry"] = expiry
    blob = {"token": token, "auth_method": data.get("auth_method") or "oauth"}
    return json.dumps(blob, ensure_ascii=False).encode("utf-8")


# ---------------------------------------------------------------- 身份

def _walk_strings(data, depth=0):
    if depth > 3:
        return
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, str):
                yield key, value
            else:
                yield from _walk_strings(value, depth + 1)
    elif isinstance(data, list):
        for value in data:
            yield from _walk_strings(value, depth + 1)


def _identity_and_email(data: dict, blob: bytes, ga):
    """尽力拿到稳定身份：JWT 里的 email > google_accounts 的 active > blob 指纹。"""
    email = ""
    for key, value in _walk_strings(data):
        if str(key).lower() in ("id_token", "access_token"):
            got = identity.email_from_jwt(value)
            if got:
                email = got
                break
    if not email and _valid_ga(ga):
        active = ga["active"].strip()
        if "@" in active:
            email = active.lower()
    if email:
        return "email:" + email, email
    ident = identity.extract(blob, ga)
    if not email:
        email = identity.email_of(ident) or (ga or {}).get("active") or ""
    return ident, email


# ---------------------------------------------------------------- 扫描

def _empty_message(root: str, ga, export_path) -> str:
    if export_path:
        return (f"{root} 里是 agys 的导出文件（{export_path}），不是 agy 数据目录。\n"
                f"直接导入它：agys import \"{export_path}\"")
    lines = [f"在 {root} 里没找到可用的 agy 登录凭据。",
             "需要一个含 refresh token 的文件，常见写法：",
             "  • oauth_creds.json（Gemini CLI 的凭据文件）",
             "  • antigravity-cli/antigravity-oauth-token（Linux 令牌文件）",
             "  • 凭据库导出的 {\"auth_method\":\"oauth\",\"token\":{...}} JSON"]
    if _valid_ga(ga):
        lines.append(f"只找到 google_accounts.json（邮箱 {ga['active']}），"
                     "但没有 token 文件，无法免登录导入。")
    return "\n".join(lines)


def scan(path: str) -> FolderAccount:
    """扫描文件夹，返回一个可直接入库的帐号。失败抛 FolderImportError。"""
    root = os.path.abspath(os.path.expanduser(path))
    if not os.path.isdir(root):
        raise FolderImportError(f"不是文件夹：{path}")

    cands, ga, export_path = [], None, None
    seen = 0
    for dirpath, dirnames, filenames in os.walk(root):
        depth = _depth_of(root, dirpath)
        if depth >= MAX_DEPTH:
            dirnames[:] = []
        else:
            dirnames[:] = sorted(d for d in dirnames
                                 if d.lower() not in SKIP_DIRS and not d.startswith("."))
        for name in sorted(filenames):
            seen += 1
            if seen > MAX_FILES:
                break
            full = os.path.join(dirpath, name)
            if name.lower() == GA_NAME:
                got = _read_json(full)
                if _valid_ga(got) and ga is None:
                    ga = got
                continue
            if name.lower() == "vault.json":     # agys 自己的库，不是 agy 凭据
                continue
            kind, data = _classify_file(full)
            if kind in ("agys-export", "agys-profile"):
                export_path = export_path or full
                continue
            if kind:
                cands.append(Candidate(full, kind, data, depth))

    if not cands:
        raise FolderImportError(_empty_message(root, ga, export_path))

    cands.sort(key=lambda c: c.priority)
    best = cands[0]
    blob = to_agy_blob(best.kind, best.data)
    ident, email = _identity_and_email(best.data, blob, ga)
    others = [f"{c.path}（{kind_label(c.kind)}）" for c in cands[1:]]
    return FolderAccount(blob=blob, kind=best.kind, source=best.path, identity=ident,
                         email=email, ga=ga, others=others, files_seen=seen)
