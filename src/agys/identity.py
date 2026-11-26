"""从 OAuth token blob 中提取稳定帐号身份。

不再依赖 google_accounts.json 的显示邮箱来判定"是不是同一个帐号"——
token 被后台刷新后邮箱字符串可能变/为空，但 email / sub claim 稳定。
"""
from __future__ import annotations

import base64
import hashlib
import json


def _jwt_claims(token: str):
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return {}
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        return json.loads(base64.urlsafe_b64decode(payload).decode("utf-8"))
    except Exception:
        return {}


def _walk(obj, depth=0):
    if depth > 8:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k, v
            yield from _walk(v, depth + 1)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v, depth + 1)


def _candidate(value):
    if isinstance(value, str) and value:
        claims = _jwt_claims(value)
        for ck in ("email", "sub"):
            if claims.get(ck):
                return ck, str(claims[ck])
    return None


def extract(blob: bytes, ga=None) -> str:
    """返回形如 'email:alice@gmail.com' / 'sub:123' / 'rt:ab12...' 的标识。"""
    data = None
    try:
        data = json.loads(blob.decode("utf-8"))
    except Exception:
        pass

    if isinstance(data, dict):
        for key, value in _walk(data):
            lk = str(key).lower()
            if lk in ("email", "account_email", "user_email") and isinstance(value, str) \
                    and "@" in value:
                return "email:" + value.strip().lower()
            if lk in ("sub", "user_id", "account_id") and isinstance(value, (str, int)):
                return "sub:" + str(value).strip().lower()
            got = _candidate(value) if isinstance(value, str) else None
            if got:
                kind, val = got
                return ("email:" if kind == "email" else "sub:") + val.lower()

    if isinstance(ga, dict):
        active = ga.get("active")
        if isinstance(active, str) and active.strip():
            a = active.strip().lower()
            return ("email:" if "@" in a else "sub:") + a

    if isinstance(data, dict):
        for key, value in _walk(data):
            if str(key).lower() in ("refresh_token", "refresh") and isinstance(value, str) and value:
                return "rt:" + hashlib.sha256(value.encode()).hexdigest()[:12]

    raw = hashlib.sha256(blob or b"").hexdigest()[:12]
    return "blob:" + raw


def email_of(identity: str) -> str:
    ident = identity or ""
    if ident.startswith("email:"):
        return ident[6:]
    return ""


def short(identity: str) -> str:
    return (identity or "").split(":", 1)[-1]
