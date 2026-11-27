"""从 OAuth token blob 中提取稳定帐号身份。

不再依赖 google_accounts.json 的显示邮箱来判定"是不是同一个帐号"——
token 被后台刷新后邮箱字符串可能变/为空，但 email / sub claim 稳定。
"""
from __future__ import annotations

import base64
import datetime
import hashlib
import json

EXPIRY_KEYS = ("expiry", "expires_at", "expiry_date", "exp")


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


def email_from_jwt(token: str) -> str:
    """从 JWT（id_token / access_token）里取 email claim；取不到返回空串。

    导入外部 agy 用户文件夹时用：那边可能只有 oauth_creds.json（没有
    google_accounts.json），邮箱只能从这个不透明 token 的 JWT 载荷里拿。
    """
    if not isinstance(token, str) or token.count(".") != 2:
        return ""
    claims = _jwt_claims(token)
    email = claims.get("email")
    return str(email).strip().lower() if email else ""


def short(identity: str) -> str:
    return (identity or "").split(":", 1)[-1]


# ---------------------------------------------------------------- token 过期

def token_expiry(blob: bytes):
    """尽力从 token blob 里解析过期时间，返回 ISO 字符串或 None。

    agy 的 blob 里字段名不完全一致（expiry / expires_at / exp），
    值可能是 epoch 秒/毫秒，也可能是 ISO 字符串，这里都尽力处理。
    """
    try:
        data = json.loads(blob.decode("utf-8"))
    except Exception:
        return None

    def walk(o, depth=0):
        if depth > 6:
            return None
        if isinstance(o, dict):
            for k, val in o.items():
                if str(k).lower() in EXPIRY_KEYS:
                    if val:
                        return val
                got = walk(val, depth + 1)
                if got:
                    return got
        elif isinstance(o, list):
            for val in o:
                got = walk(val, depth + 1)
                if got:
                    return got
        return None

    raw = walk(data)
    if raw is None:
        return None
    try:
        if isinstance(raw, (int, float)) or str(raw).isdigit():
            ts = float(raw)
            if ts > 1e12:
                ts /= 1000.0
            return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).isoformat()
        return str(raw)
    except Exception:
        return str(raw)


def expiry_dt(raw):
    """把 token_expiry 的返回值解析成 aware datetime；失败返回 None。"""
    if not raw:
        return None
    s = str(raw).strip().replace("Z", "+00:00")
    try:
        dt = datetime.datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt


def expiry_age(raw, now=None):
    """距过期还剩多少秒；已过期为负；解析失败返回 None。"""
    dt = expiry_dt(raw)
    if dt is None:
        return None
    now = now or datetime.datetime.now(datetime.timezone.utc)
    return (dt - now).total_seconds()


def expiry_human(raw, now=None):
    """剩余时间的中文短描述：3 天 / 5 小时 / 已过期 2 天；未知返回空串。"""
    sec = expiry_age(raw, now)
    if sec is None:
        return ""
    if sec < 0:
        return "已过期 " + _span(-sec)
    return _span(sec)


def _span(sec):
    sec = int(abs(sec))
    if sec >= 86400 * 2:
        return f"{sec // 86400} 天"
    if sec >= 3600:
        return f"{sec // 3600} 小时"
    if sec >= 60:
        return f"{sec // 60} 分钟"
    return f"{max(sec, 1)} 秒"
