"""代理配置：只注入 agys 启动的子进程，绝不修改系统代理。

优先级：`AGYS_NO_PROXY=1`（本次禁用） > `AGYS_PROXY` 环境变量 > 配置文件
`~/.agy-accounts/config.json`。

配置文件权限 0600——代理 URL 可能含账号密码，`agys proxy show` 会打码展示。
"""
from __future__ import annotations

import json
import os
import socket
import urllib.parse
import urllib.request

from .common import AgysError
from .config import paths
from .crypto import secure_write

SCHEMES = ("http", "https", "socks5", "socks5h", "socks4")
DEFAULT_NO_PROXY = ("localhost", "127.0.0.1", "::1")
DEFAULT_PORTS = {"http": 80, "https": 443, "socks5": 1080, "socks5h": 1080, "socks4": 1080}


def normalize(url: str) -> str:
    """补全 scheme 并校验。空串表示未配置。"""
    u = (url or "").strip()
    if not u:
        return ""
    if "://" not in u:
        u = "http://" + u
    if "'" in u or '"' in u or " " in u:
        raise AgysError("代理地址不能包含引号或空格")
    p = urllib.parse.urlsplit(u)
    scheme = (p.scheme or "").lower()
    if scheme not in SCHEMES:
        raise AgysError(f"不支持的代理协议 '{p.scheme}'，可选：{', '.join(SCHEMES)}")
    if not p.hostname:
        raise AgysError(f"代理地址缺少主机名：{u}")
    try:
        p.port  # 触发非法端口校验
    except ValueError:
        raise AgysError(f"代理端口不合法：{u}")
    return u


def mask(url: str) -> str:
    """隐藏 URL 中的密码，用于展示。"""
    if not url:
        return ""
    p = urllib.parse.urlsplit(url)
    if not p.password:
        return url
    host = p.hostname or ""
    if p.port:
        host = f"{host}:{p.port}"
    netloc = f"{p.username or ''}:***@{host}"
    return urllib.parse.urlunsplit((p.scheme, netloc, p.path, p.query, p.fragment))


def load() -> dict:
    try:
        with open(paths().config_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, ValueError, OSError):
        return {}


def save(cfg: dict) -> None:
    data = (json.dumps(cfg, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    secure_write(paths().config_file, data)


def set_proxy(url: str, no_proxy=None) -> str:
    u = normalize(url)
    if not u:
        raise AgysError("代理地址不能为空；要清除请用 agys proxy clear")
    cfg = load()
    cfg["proxy"] = u
    if no_proxy is not None:
        cfg["no_proxy"] = str(no_proxy).strip()
    save(cfg)
    return u


def clear_proxy() -> None:
    cfg = load()
    cfg.pop("proxy", None)
    cfg.pop("no_proxy", None)
    save(cfg)


def current():
    """返回当前生效的代理 URL；未配置返回 None。"""
    if os.environ.get("AGYS_NO_PROXY") == "1":
        return None
    env = (os.environ.get("AGYS_PROXY") or "").strip()
    if env:
        return normalize(env) or None
    stored = (load().get("proxy") or "").strip()
    return normalize(stored) if stored else None


def no_proxy_entries(base=None):
    """返回 NO_PROXY 条目；base 给定时从该环境字典继承，否则读当前进程环境。"""
    cfg = load()
    raw = cfg.get("no_proxy")
    if raw is None:
        src = os.environ if base is None else base
        raw = src.get("NO_PROXY") or src.get("no_proxy") or ""
    items = [x.strip() for x in str(raw).split(",") if x.strip()]
    for d in DEFAULT_NO_PROXY:
        if d not in items:
            items.append(d)
    return items


def child_env(base=None) -> dict:
    """给子进程用的环境变量；未配置代理时原样返回。"""
    env = dict(os.environ if base is None else base)
    p = current()
    if not p:
        return env
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        env[key] = p
        env[key.lower()] = p
    joined = ",".join(no_proxy_entries(env))
    env["NO_PROXY"] = joined
    env["no_proxy"] = joined
    return env


def is_socks(url) -> bool:
    return (url or "").lower().startswith(("socks5://", "socks5h://", "socks4://"))


def urlopen(url, timeout=15):
    """带代理的 urlopen；urllib 不支持 socks，遇到 socks 退回直连。"""
    p = current()
    if p and not is_socks(p):
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": p, "https": p}))
        return opener.open(url, timeout=timeout)
    return urllib.request.urlopen(url, timeout=timeout)


def test(url=None, timeout=5):
    """TCP 连通性测试，返回 (ok, 说明)。"""
    u = normalize(url) if url else current()
    if not u:
        return False, "未配置代理"
    p = urllib.parse.urlsplit(u)
    host = p.hostname
    try:
        port = p.port or DEFAULT_PORTS.get((p.scheme or "").lower(), 0)
    except ValueError:
        return False, f"代理端口不合法：{u}"
    if not host or not port:
        return False, f"代理地址不完整：{u}"
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, f"{host}:{port} 可连接"
    except OSError as e:
        return False, f"无法连接 {host}:{port}（{e}）"
