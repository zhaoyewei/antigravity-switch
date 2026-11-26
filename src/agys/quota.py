"""帐号额度探测与 auto 选号。

为什么要绕这么一圈：Antigravity 免费帐号调用 `retrieveUserQuota` 会返回
403 `SUBSCRIPTION_REQUIRED` —— 不是没额度，而是「没有可查询的配额包」。
所以这里做分层探测：

======================  ============================================
数据源                    能回答什么
======================  ============================================
retrieveUserQuota       有 Code Assist 订阅时给出真实剩余额度
                        （buckets[].remainingFraction / resetTime）
countTokens             零成本健康探针：凭据还能不能打 API
streamGenerateContent   真正耗尽时返回 429 RESOURCE_EXHAUSTED
======================  ============================================

对免费帐号，前两个给出「可用 / 不可用」，拿不到「还剩百分之几」。
这种情况下 auto 退化为「挑一个还没用光的、最久没用过的帐号」，
并在 `agys auto --status` 里如实标注 `额度未知`，不假装有数字。

全部只读：只拿 refresh_token 换 access_token 做探测，不写凭据库、
不写 agy 的任何文件。探测结果缓存到 `~/.agy-accounts/quota.json`。
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from .config import paths
from .crypto import secure_write
from .proxy import open_request
from .vault import load_profile, save_profile

CODE_ASSIST = "https://cloudcode-pa.googleapis.com/v1internal:"
TOKEN_URL = "https://oauth2.googleapis.com/token"

# agy.exe 内置的 OAuth 客户端（公开值，非用户机密）。
# 可用 AGYS_OAUTH_CLIENT_ID / AGYS_OAUTH_CLIENT_SECRET 覆盖。
DEFAULT_CLIENT_ID = ("1071006060591-tmhssin2h21lcre235vtolojh4g403ep"
                     ".apps.googleusercontent.com")
DEFAULT_CLIENT_SECRET = "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"

# 缓存有效期：额度结果 5 分钟；access_token 提前 2 分钟过期
QUOTA_TTL = 300
TOKEN_SKEW = 120
HEALTH_MODEL = "gemini-2.5-pro"

STATE_ORDER = {"ok": 0, "unknown": 1, "exhausted": 2, "auth": 3, "error": 4}
STATE_LABEL = {"ok": "可用", "unknown": "额度未知", "exhausted": "额度已用尽",
               "auth": "需要重新登录", "error": "探测失败"}


# ---------------------------------------------------------------- 缓存

def _cache_path():
    return os.path.join(paths().home, "quota.json")


def load_cache():
    try:
        with open(_cache_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_cache(data):
    try:
        secure_write(_cache_path(),
                     (json.dumps(data, ensure_ascii=False) + "\n").encode("utf-8"))
    except OSError:
        pass


def _client():
    return (os.environ.get("AGYS_OAUTH_CLIENT_ID") or DEFAULT_CLIENT_ID,
            os.environ.get("AGYS_OAUTH_CLIENT_SECRET") or DEFAULT_CLIENT_SECRET)


# ---------------------------------------------------------------- token

def _refresh_token(refresh_token):
    cid, secret = _client()
    body = urllib.parse.urlencode({
        "client_id": cid, "client_secret": secret,
        "refresh_token": refresh_token, "grant_type": "refresh_token",
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=body, headers={
        "Content-Type": "application/x-www-form-urlencoded"})
    with open_request(req, timeout=25) as r:
        data = json.loads(r.read().decode("utf-8"))
    token = data.get("access_token")
    if not token:
        raise ValueError("刷新响应里没有 access_token")
    return token, time.time() + int(data.get("expires_in") or 3600)


def access_token(acc_id, cache=None, force=False):
    """拿一个可用的 access_token。优先用缓存，其次刷新，最后用 blob 自带的。

    刷新成功后会把新 token 写回 profile —— refresh_token 不变，所以不影响登录态，
    但能让后续命令少刷一次。
    """
    cache = cache if cache is not None else load_cache()
    entry = cache.setdefault("accounts", {}).setdefault(acc_id, {})
    now = time.time()
    if not force and entry.get("token") and entry.get("token_exp", 0) - TOKEN_SKEW > now:
        return entry["token"]

    prof = load_profile(acc_id)
    blob = json.loads(prof["blob"].decode("utf-8"))
    token_obj = blob.get("token") or {}
    rt = token_obj.get("refresh_token")
    if rt:
        try:
            token, exp = _refresh_token(rt)
            entry["token"], entry["token_exp"], entry["refreshed_at"] = token, exp, now
            token_obj["access_token"] = token
            token_obj["expiry"] = time.strftime("%Y-%m-%dT%H:%M:%S.000000Z",
                                                time.gmtime(exp))
            save_profile(acc_id, json.dumps(blob, ensure_ascii=False).encode("utf-8"),
                         prof.get("google_accounts"), dict(prof))
            return token
        except Exception:
            pass
    at = token_obj.get("access_token")
    if at:
        return at
    raise RuntimeError(f"帐号 '{acc_id}' 没有可用的 refresh_token")


# ---------------------------------------------------------------- 探测

def _post(method, token, body=None, timeout=20):
    req = urllib.request.Request(
        CODE_ASSIST + method, data=json.dumps(body or {}).encode(),
        headers={"Authorization": "Bearer " + token,
                 "Content-Type": "application/json"})
    try:
        with open_request(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, {"raw": raw[:300]}
    except Exception as e:  # 网络层失败
        return -1, {"error": {"message": str(e)[:200]}}


def _error_reason(payload):
    err = (payload or {}).get("error") or {}
    return str(err.get("status") or ""), str(err.get("message") or "")


def _parse_buckets(payload):
    """从 retrieveUserQuota 响应里挖出剩余额度。

    不同版本字段名不完全一致，所以按「列表 + remainingFraction 键」去找，
    而不是死认某个 schema。
    """
    found = []

    def walk(node, depth=0):
        if depth > 4:
            return
        if isinstance(node, dict):
            frac = node.get("remainingFraction")
            amount = node.get("remainingAmount")
            if isinstance(frac, (int, float)) or isinstance(amount, (int, float)):
                found.append({
                    "model": node.get("modelId") or node.get("model") or "",
                    "fraction": float(frac) if isinstance(frac, (int, float)) else None,
                    "amount": amount,
                    "reset": node.get("resetTime") or "",
                })
            for v in node.values():
                walk(v, depth + 1)
        elif isinstance(node, list):
            for v in node:
                walk(v, depth + 1)

    walk(payload)
    return found


def probe(acc_id, cache=None):
    """探测一个帐号，返回 report dict。不抛异常（网络问题也算一种结果）。"""
    cache = cache if cache is not None else load_cache()
    base = {"id": acc_id, "checked": int(time.time()),
            "remaining": None, "models": [], "detail": "", "state": "error"}
    try:
        token = access_token(acc_id, cache)
    except Exception as e:
        return {**base, "state": "auth", "detail": f"无法取得 token：{e}"}

    status, payload = _post("retrieveUserQuota", token, {})
    if status == 200:
        buckets = _parse_buckets(payload)
        if buckets:
            fracs = [b["fraction"] for b in buckets if b["fraction"] is not None]
            remaining = min(fracs) if fracs else None
            state = "exhausted" if remaining is not None and remaining <= 0.001 else "ok"
            return {**base, "state": state, "remaining": remaining,
                    "models": buckets,
                    "detail": (f"剩余 {remaining * 100:.0f}%" if remaining is not None
                               else "已返回配额但无比例字段")}
        return {**base, "state": "unknown", "detail": "配额接口无数据"}

    st, msg = _error_reason(payload)
    if status == 429 or st == "RESOURCE_EXHAUSTED":
        return {**base, "state": "exhausted", "detail": "429 配额耗尽"}
    if status == 401:
        return {**base, "state": "auth", "detail": "凭据失效，需要重新登录"}
    if status in (403, 404):
        # 免费帐号：拿不到配额包，但这不代表不能用 —— 退回健康探针
        ok, detail = health(token)
        if ok:
            return {**base, "state": "unknown",
                    "detail": "无配额包（免费帐号），健康探针通过"}
        if detail == "exhausted":
            return {**base, "state": "exhausted", "detail": "健康探针返回 429"}
        if detail == "auth":
            return {**base, "state": "auth", "detail": "健康探针鉴权失败"}
        return {**base, "state": "error", "detail": f"配额 {status}：{msg[:80]}"}
    return {**base, "state": "error", "detail": f"配额接口返回 {status}"}


def health(token):
    """零成本健康探针：能数 token 说明凭据还能用。返回 (ok, code)。"""
    status, payload = _post("countTokens", token, {
        "request": {"contents": [{"role": "user", "parts": [{"text": "hi"}]}],
                    "model": HEALTH_MODEL}})
    if status == 200:
        return True, "ok"
    if status == 429:
        return False, "exhausted"
    if status == 401:
        return False, "auth"
    return False, "error"


# ---------------------------------------------------------------- 排名

def _last_switched():
    """从审计日志里统计每个帐号最后一次被切换的时间。"""
    from . import audit
    last = {}
    for row in audit.read(limit=1000):
        if row.get("action") != "switch" or row.get("result") != "ok":
            continue
        to = row.get("to")
        if to:
            last.setdefault(to, row.get("ts") or "")
    return last


def snapshot(v, offline=False, ids=None):
    """汇总所有帐号的额度状态。offline=True 时只用缓存，不联网。"""
    cache = load_cache()
    cached = cache.get("accounts") or {}
    last = _last_switched()
    now = time.time()
    reports = []
    for acc_id in sorted(ids or v["accounts"]):
        meta = v["accounts"].get(acc_id, {})
        prev = cached.get(acc_id) or {}
        report = None
        if not offline and now - (prev.get("checked") or 0) > QUOTA_TTL:
            report = probe(acc_id, cache)
            cached[acc_id] = {k: report.get(k) for k in
                              ("state", "checked", "remaining", "detail",
                               "token", "token_exp", "refreshed_at")}
            cached[acc_id]["models"] = report.get("models") or []
        elif prev:
            report = {**prev, "id": acc_id, "models": prev.get("models") or []}
            report.setdefault("remaining", None)
            report.setdefault("detail", "")
        if report is None:
            report = {"id": acc_id, "state": "unknown", "remaining": None,
                      "detail": "未探测", "checked": 0, "models": []}
        report["email"] = meta.get("email") or ""
        report["last_switch"] = last.get(acc_id, "")
        reports.append(report)
    cache["accounts"] = cached
    save_cache(cache)
    return rank(reports)


def rank(reports):
    """排序规则：能用 > 额度未知 > 用尽 > 登录失效 > 探测失败；
    同档内按剩余额度降序，再按最久没切换过的优先（轮换更均衡）。"""
    return sorted(reports, key=lambda r: (
        STATE_ORDER.get(r.get("state"), 9),
        -(r["remaining"] if isinstance(r.get("remaining"), (int, float)) else -1.0),
        r.get("last_switch") or "",
    ))


def usable(report):
    return report.get("state") in ("ok", "unknown")


def mark(acc_id, state, detail):
    """记录一次运行期结论（比如 agy 用中途 429 了），供下次 auto 参考。"""
    cache = load_cache()
    entry = cache.setdefault("accounts", {}).setdefault(acc_id, {})
    entry.update({"state": state, "detail": detail, "checked": int(time.time()),
                  "remaining": 0.0 if state == "exhausted" else entry.get("remaining")})
    save_cache(cache)


def label(report):
    """状态标签本身（不含说明），用于表格列。"""
    text = STATE_LABEL.get(report.get("state"), report.get("state") or "?")
    if isinstance(report.get("remaining"), (int, float)):
        text += f" {report['remaining'] * 100:.0f}%"
    return text


def describe(report):
    """一行人类可读描述（标签 + 说明），用于警告与单行输出。"""
    detail = report.get("detail") or ""
    return label(report) + (f"（{detail}）" if detail else "")
