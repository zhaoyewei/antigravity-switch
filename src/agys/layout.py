"""存储布局探测与自动适配。

agy 升级可能换掉存储位置，写死路径会静默失效。这里的策略是
「自动发现 + 自动兼容，但不做数据迁移」：

1. **结构指纹**只包含真正决定「往哪写」的字段：平台 / 凭据后端 / 凭据条目名 /
   `google_accounts.json` 路径 / 受控 token 路径。agy 版本号只记录、不参与判断，
   因此 agy 升级本身不会再拦住切换。
2. 指纹变化，或「有活跃凭据但状态文件不见了」时，自动在已知候选位置里搜索
   真正生效的那一套（候选凭据条目 / 状态文件 / 受控 token 路径）。
3. 候选布局必须通过三道探测关卡才会被采纳：新指纹确实不同、新位置确实有数据、
   新旧位置的身份一致。采纳只是**更新指针**，不搬文件、不改格式；任何一步
   无法确认，就退回「拒绝切换」，绝不猜测。
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys

from . import audit, identity
from .common import read_ga
from .config import (
    DEFAULT_CRED_TARGET, IS_WIN, agy_argv, agy_binary, get_overrides, paths,
    set_overrides,
)
from .credentials import CredentialError, build_store
from .vault import now_iso, save_vault

# 只有这些字段参与结构指纹：它们决定 agys 到底往哪儿写。
STRUCT_KEYS = ("platform", "backend", "cred_target", "ga_path", "token_path")
# 仅记录、不参与判断（agy 升级会改版本号，IDE 状态库只是只读参考）
INFO_KEYS = ("agy_version", "ide_state_path")

_GA_NAME = "google_accounts.json"
_TOKEN_NAME = "antigravity-oauth-token"
# 搜索时跳过的目录：体积大、不可能放 agy 凭据
_SKIP_DIRS = {
    ".git", ".svn", ".hg", "__pycache__", "node_modules", "site-packages",
    ".venv", "venv", "Cache", "Caches", ".cache", "Temp", "temp", "tmp",
    "Packages", "Microsoft", "assembly", "logs", "Logs", "Crashpad",
}
# 路径里出现这些片段才算「agy 的」文件，避免捡到别的 Google 工具的同名文件
_OWNER_HINTS = {"gemini", ".gemini", "antigravity", "antigravity-cli", "agy"}


def agy_version() -> str:
    argv = agy_argv(["--version"])
    if not argv:
        return "unknown"
    try:
        # 不能用 text=True：Windows 下 agy 可能输出非当前代码页的字节，
        # 解码失败会在 reader 线程里抛异常（版本号只是展示用，不该影响命令）
        r = subprocess.run(argv, capture_output=True, timeout=15)
        if r.returncode == 0 and r.stdout and r.stdout.strip():
            text = r.stdout.decode("utf-8", "replace").strip()
            return text.splitlines()[0].strip()
    except Exception:
        pass
    return "unknown"


def ide_state_path():
    if IS_WIN:
        base = os.environ.get("APPDATA") or os.path.join(
            os.path.expanduser("~"), "AppData", "Roaming")
        return os.path.join(base, "Antigravity IDE", "User", "globalStorage", "state.vscdb")
    if sys.platform == "darwin":
        return os.path.join(os.path.expanduser("~"), "Library", "Application Support",
                            "Antigravity IDE", "User", "globalStorage", "state.vscdb")
    return os.path.join(os.path.expanduser("~"), ".config", "Antigravity IDE",
                        "User", "globalStorage", "state.vscdb")


def _platform() -> str:
    return "windows" if IS_WIN else "macos" if sys.platform == "darwin" else "linux"


def _struct(fields: dict) -> dict:
    return {k: fields.get(k) for k in STRUCT_KEYS}


def _fp(data: dict) -> str:
    raw = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _safe_get(store):
    if not hasattr(store, "get"):
        return None
    try:
        return store.get()
    except (CredentialError, OSError, KeyError):
        return None


def probe(store, overrides=None) -> dict:
    p = paths()
    fields = {
        "platform": _platform(),
        "backend": store.name,
        "cred_target": p.cred_target,
        "ga_path": p.ga,
        "token_path": p.linux_token,
        "agy_version": agy_version(),
        "ide_state_path": ide_state_path(),
    }
    struct = _struct(fields)
    return {
        **fields,
        "structure": struct,
        "fingerprint": _fp(struct),
        "overrides": dict(overrides if overrides is not None else get_overrides()),
        "has_credential": _safe_get(store) is not None,
        "ga_exists": os.path.isfile(p.ga),
        "token_exists": os.path.isfile(p.linux_token),
        "ide_state_exists": os.path.isfile(fields["ide_state_path"]),
        "agy_binary": agy_binary(),
    }


# ---------------------------------------------------------------- 缓存读写

def _remember(vault, cur, overrides=None):
    entry = {k: v for k, v in cur.items() if not k.startswith("_")}
    ov = overrides if overrides is not None else (cur.get("overrides") or {})
    entry["overrides"] = {k: v for k, v in (ov or {}).items() if v}
    entry["adopted_at"] = now_iso()
    vault["layout"] = entry
    save_vault(vault)


def _cached_struct_fp(cached: dict) -> str:
    if not cached:
        return ""
    struct = cached.get("structure")
    if isinstance(struct, dict) and struct:
        return _fp(_struct(struct))
    # v0.4 之前的缓存没有 structure 字段：用同一套结构字段回算。
    # 那次算进去的 agy_version 直接忽略，升级不会造成假变化。
    return _fp({k: cached.get(k) for k in STRUCT_KEYS})


def _cached_value(cached: dict, key: str):
    struct = cached.get("structure")
    if isinstance(struct, dict) and key in struct:
        return struct.get(key)
    return cached.get(key)


def _diff(cached: dict, cur: dict):
    out = []
    for k in STRUCT_KEYS:
        old = _cached_value(cached, k)
        if old != cur.get(k):
            out.append(f"{k}: {old!r} -> {cur.get(k)!r}")
    return out


def _override_alive(key: str, value: str) -> bool:
    """覆盖值是否还活着。丢弃陈旧指针后 verify() 会重新发现或明确报错。"""
    if key == "cred_target":
        try:
            if _safe_get(build_store(None, cred_target=value)) is not None:
                return True
            return _safe_get(build_store(None)) is None
        except (CredentialError, OSError):
            return False
    return os.path.isdir(os.path.dirname(value) or ".")


def apply_cached(vault) -> bool:
    """把上次采纳的布局写进进程级配置。

    必须在 `get_store()` 之前调用，否则凭据后端仍按默认路径构造。
    """
    set_overrides(None)  # 先回到干净基线，_override_alive() 的对比才有意义
    cached = (vault or {}).get("layout") or {}
    ov = cached.get("overrides") or {}
    usable = {}
    for key in ("cred_target", "ga", "linux_token"):
        value = ov.get(key)
        if value and _override_alive(key, value):
            usable[key] = value
    set_overrides(usable or None)
    return bool(usable)


# ---------------------------------------------------------------- 自动发现

def _search_roots():
    p = paths()
    gem = p.gemini_home.rstrip("\\/")
    home = os.path.dirname(gem) or os.path.expanduser("~")
    roots = [gem, home]
    if IS_WIN:
        for env in ("APPDATA", "LOCALAPPDATA"):
            base = os.environ.get(env)
            if base:
                roots += [os.path.join(base, "Antigravity"),
                          os.path.join(base, "agy"),
                          os.path.join(base, "Gemini")]
    elif sys.platform == "darwin":
        roots.append(os.path.join(home, "Library", "Application Support"))
    else:
        roots.append(os.path.join(home, ".config"))
    out = []
    for r in roots:
        if r and os.path.isdir(r) and r not in out:
            out.append(r)
    return out


def _owned(path: str) -> bool:
    parts = path.lower().replace("\\", "/").split("/")
    return any(p in _OWNER_HINTS for p in parts if p)


def _find_files(name: str, max_depth=3, cap=6000):
    """在有限范围里找同名文件。范围/深度/目录数都设上限，避免拖慢每条命令。"""
    hits, visited = [], 0
    for root in _search_roots():
        base = root.rstrip("\\/").count(os.sep)
        for dirpath, dirnames, filenames in os.walk(root):
            visited += 1
            if visited > cap:
                return hits
            depth = dirpath.rstrip("\\/").count(os.sep) - base
            if depth >= max_depth:
                dirnames[:] = []
            else:
                dirnames[:] = [d for d in dirnames
                               if d not in _SKIP_DIRS and not d.startswith(".")]
            if name in filenames:
                hit = os.path.join(dirpath, name)
                if _owned(hit) and hit not in hits:
                    hits.append(hit)
    return hits


def _valid_ga(path: str) -> bool:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and isinstance(data.get("active"), str) \
        and bool(data["active"].strip())


def _valid_token(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            return bool(f.read(16).strip())
    except OSError:
        return False


def _ga_candidates():
    out = [os.path.join(paths().gemini_home, _GA_NAME)]
    for hit in _find_files(_GA_NAME):
        if hit not in out and _valid_ga(hit):
            out.append(hit)
    return out


def _token_candidates():
    out = [os.path.join(paths().gemini_home, "antigravity-cli", _TOKEN_NAME)]
    for hit in _find_files(_TOKEN_NAME):
        if hit not in out and _valid_token(hit):
            out.append(hit)
    return out


def _target_candidates():
    out = [DEFAULT_CRED_TARGET]
    if not IS_WIN:
        return out
    try:
        from .credentials.windows import list_targets
        names = list_targets()
    except Exception:
        names = []
    for n in names:
        low = n.lower()
        if n not in out and ("antigravity" in low or "gemini" in low):
            out.append(n)
    return out


def _pinned_keys():
    """被环境变量显式钉住的维度。这些是用户的明确配置，自动发现不该去改它。"""
    out = set()
    if os.environ.get("AGYS_CRED_TARGET"):
        out.add("cred_target")
    if os.environ.get("AGYS_BACKEND"):
        out.add("backend")
    if os.environ.get("AGYS_GEMINI_HOME"):
        out |= {"ga_path", "token_path"}
    return out


def _baseline_overrides():
    gem = paths().gemini_home
    return {
        "cred_target": DEFAULT_CRED_TARGET,
        "ga": os.path.join(gem, _GA_NAME),
        "linux_token": os.path.join(gem, "antigravity-cli", _TOKEN_NAME),
    }


def _candidate_overrides():
    """按维度生成候选覆盖，默认布局排第一。"""
    seen = {}
    pinned = _pinned_keys()
    base = _baseline_overrides()

    def add(d):
        keep = {}
        for k, v in d.items():
            if not v:
                continue
            if k == "cred_target" and "cred_target" in pinned:
                continue
            if k in ("ga", "linux_token") and "ga_path" in pinned:
                continue
            if v == base.get(k):      # 和基线一致就不算覆盖
                continue
            keep[k] = v
        key = (keep.get("cred_target", ""), keep.get("ga", ""),
               keep.get("linux_token", ""))
        if key not in seen:
            seen[key] = keep

    gases = _ga_candidates()
    tokens = _token_candidates()
    add({})
    for t in _target_candidates():
        add({"cred_target": t})
    for g in gases:
        add({"ga": g})
    for t in tokens:
        add({"linux_token": t})
    # 整套目录一起搬走是最常见的情况：把非默认的组合也铺开
    for g in gases[1:]:
        for t in tokens:
            add({"ga": g, "linux_token": t})
    for t in tokens[1:]:
        add({"ga": gases[0], "linux_token": t})
    return list(seen.values())


def _probe_overrides(ov: dict) -> dict:
    saved = get_overrides()
    set_overrides(ov)
    try:
        store = build_store(None, ov.get("cred_target"), None, ov.get("linux_token"))
        cur = probe(store, overrides=ov)
    finally:
        set_overrides(saved)
    return cur


def _blob_for(ov: dict):
    try:
        return _safe_get(build_store(None, ov.get("cred_target"), None,
                                     ov.get("linux_token")))
    except (CredentialError, OSError):
        return None


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def discover(store=None):
    """列出候选布局（含默认布局），只读探测，不写任何东西。"""
    out, seen = [], set()
    for ov in _candidate_overrides():
        try:
            cur = _probe_overrides(ov)
        except (CredentialError, OSError):
            continue
        if cur["fingerprint"] in seen:      # 不同覆盖组合可能指向同一套位置
            continue
        seen.add(cur["fingerprint"])
        out.append(cur)
    return out


# ---------------------------------------------------------------- 自动兼容

def _is_dead(cur: dict) -> bool:
    """有活跃凭据、状态文件却不见了 —— 大概率 agy 换了存储位置。"""
    if cur.get("backend") == "memory" or not cur.get("has_credential"):
        return False
    if cur.get("backend") == "linux":
        return not cur.get("token_exists")
    return not cur.get("ga_exists")


def _try_adopt(vault, store, cur, old_fp):
    old_blob = _safe_get(store)
    old_ident = identity.extract(old_blob, read_ga()) if old_blob else None

    cands = [c for c in discover(store) if c["fingerprint"] != old_fp]
    # 有凭据的候选优先，其次只看状态文件
    cands.sort(key=lambda c: (bool(c["has_credential"]),
                              bool(c["ga_exists"] or c["token_exists"])),
               reverse=True)
    for c in cands:
        ov = c.get("overrides") or {}
        if not (c["has_credential"] or c["ga_exists"] or c["token_exists"]):
            continue                      # 关卡 1：新位置确实有东西
        if old_blob is not None and not c["has_credential"]:
            continue                      # 关卡 2：旧位置能读、新位置读不到 = 误发现
        if old_ident and c["has_credential"]:
            new_ident = identity.extract(_blob_for(ov), _read_json(c["ga_path"]))
            if new_ident != old_ident:
                continue                  # 关卡 3：身份不一致，说明不是同一个登录态
        _remember(vault, c, ov)
        audit.log("layout-adopt", detail=json.dumps(
            {"from": old_fp, "to": c["fingerprint"], "overrides": ov},
            ensure_ascii=False))
        desc = ", ".join(f"{k}={v}" for k, v in ov.items()) or "默认位置"
        return True, (f"已自动适配 agy 存储布局（{desc}），指纹 "
                      f"{old_fp or '-'} -> {c['fingerprint']}；未搬迁任何数据")
    return False, ""


def adopt_current(vault, store):
    """把当前探测到的布局记为基准（手动放行）。"""
    cur = probe(store)
    _remember(vault, cur)
    audit.log("layout-adopt", detail=f"manual accept {cur['fingerprint']}")
    return cur


def adopt_best(vault, store):
    """手动触发一次自动发现，返回 (ok, message)。"""
    cur = probe(store)
    cached = (vault or {}).get("layout") or {}
    return _try_adopt(vault, store, cur, _cached_struct_fp(cached))


def verify(vault, store, allow_change=False):
    """返回 (ok, message)。首次运行自动记录布局。"""
    cur = probe(store)
    cached = vault.get("layout")
    if not cached:
        _remember(vault, cur)
        return True, f"已记录存储布局指纹 {cur['fingerprint']}（agy {cur['agy_version']}）"

    old_fp = _cached_struct_fp(cached)
    if allow_change:
        if old_fp != cur["fingerprint"] or cached.get("agy_version") != cur["agy_version"]:
            diff = _diff(cached, cur)
            _remember(vault, cur)
            return True, ("存储布局已按当前状态更新"
                          + ("：" + "; ".join(diff) if diff else
                             f"（agy {cur['agy_version']}）"))
        return True, ""

    if old_fp == cur["fingerprint"] and not _is_dead(cur):
        # 结构没变：版本号变了只更新记录，不再拦截（升级不该阻断切换）
        bumped = cached.get("agy_version") != cur["agy_version"]
        stale = cached.get("fingerprint") != cur["fingerprint"]  # v0.4 缓存格式
        if bumped or stale:
            old_ver = cached.get("agy_version") or "unknown"
            _remember(vault, cur)
            if bumped:
                return True, (f"agy 版本 {old_ver} -> {cur['agy_version']}，"
                              "存储结构未变，已更新记录")
        return True, ""

    # 变化全部来自用户显式设置的环境变量：这是明确配置，不是 agy 偷偷换了位置
    changed = {k for k in STRUCT_KEYS if _cached_value(cached, k) != cur.get(k)}
    if changed and changed <= _pinned_keys():
        _remember(vault, cur)
        return True, ("检测到你通过环境变量指定了存储位置，已更新基准布局："
                      + "; ".join(_diff(cached, cur)))

    ok, msg = _try_adopt(vault, store, cur, old_fp)
    if ok:
        return True, msg

    diff = _diff(cached, cur)
    if old_fp == cur["fingerprint"]:
        # 结构一致、只是状态文件暂时不在：不阻断，交给 doctor 提醒
        return True, ("活跃凭据存在但状态文件缺失（"
                      + ("token" if cur.get("backend") == "linux" else "google_accounts.json")
                      + "），已知位置未找到更合适的布局，继续按当前布局执行")

    return False, (
        "检测到 agy 存储布局变化，自动发现在已知位置没找到可用的新布局：\n  "
        + ("\n  ".join(diff) or "结构指纹变化")
        + "\n已拒绝切换，避免把凭据写到 agy 不再读取的位置。\n"
          "排查：agys layout 看探测结果，agys layout --discover 看候选布局；"
          "确认无误后可 agys layout --adopt 采纳当前布局，或加 --allow-layout-change 放行。")


def live_identity(store, ga):
    blob = store.get()
    if blob is None:
        return None
    return identity.extract(blob, ga)
