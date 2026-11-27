"""环境自检：输出结构化数据，便于 --json 与 CI 使用。"""
from __future__ import annotations

import json
import os
import sys

from . import __version__
from .config import IS_WIN, agy_binary, paths
from .crypto import CryptoError
from .layout import agy_version, ide_state_path, probe
from .vault import load_profile, load_vault


def collect(store):
    p = paths()
    v = load_vault()
    live = None
    try:
        live = store.get()
    except Exception as e:
        live = None
        store_error = str(e)
    else:
        store_error = None
    from . import identity
    live_ident = identity.extract(live, _read_ga()) if live else None
    matched = None
    if live_ident:
        for acc in v["accounts"]:
            try:
                if load_profile(acc).get("identity") == live_ident:
                    matched = acc
                    break
            except (KeyError, CryptoError):
                continue
    profiles = []
    for acc in sorted(v["accounts"]):
        try:
            prof = load_profile(acc)
            expiry = identity.token_expiry(prof["blob"])
            profiles.append({"id": acc, "ok": bool(prof["blob"]),
                             "bytes": len(prof["blob"]), "identity": prof.get("identity"),
                             "token_expiry": expiry})
        except (KeyError, CryptoError) as e:
            profiles.append({"id": acc, "ok": False, "error": str(e)})
    from .process import describe, list_procs
    procs = list_procs()
    layout = probe(store)
    warnings = []
    if store_error:
        warnings.append(f"凭据库读取失败：{store_error}")
    if live and not matched:
        warnings.append("活跃凭据未纳入管理，下次 use/add 会自动收录")
    if v.get("current") and v["current"] != matched and live:
        warnings.append("vault 记录的当前帐号与活跃凭据不一致")
    if not IS_WIN and not p.no_encrypt and not os.path.isfile(p.key_file):
        warnings.append("加密密钥文件缺失（首次写入时会自动创建）")
    if os.path.isfile(p.pending):
        warnings.append("存在未完成事务（下次启动会自动回滚）")
    if p.no_encrypt:
        warnings.append("AGYS_NO_ENCRYPT=1：本地凭据以明文存储")
    cached_layout = v.get("layout") or {}
    if cached_layout and cached_layout.get("fingerprint") != layout["fingerprint"]:
        warnings.append("存储布局指纹与缓存不一致（升级后首次写入时可能自动适配，"
                        "也可运行 agys layout --discover 查看候选）")
    if live and not (layout["token_exists"] if layout["backend"] == "linux"
                     else layout["ga_exists"]):
        warnings.append("有活跃凭据但状态文件不存在，agy 可能已换存储位置"
                        "（运行 agys layout --discover 查看候选）")
    # token 过期预警：已过期或 48 小时内过期的帐号值得提前知道
    for pr in profiles:
        if not pr.get("token_expiry"):
            continue
        age = identity.expiry_age(pr["token_expiry"])
        if age is None:
            continue
        if age <= 0:
            warnings.append(f"帐号 '{pr['id']}' 的 token 已过期（{identity.expiry_human(pr['token_expiry'])}），"
                            "刷新失败时需要重新登录")
        elif age < 48 * 3600:
            warnings.append(f"帐号 '{pr['id']}' 的 token 将在 "
                            f"{identity.expiry_human(pr['token_expiry'])}内过期")
    return {
        "version": __version__,
        "platform": sys.platform,
        "python": sys.version.split()[0],
        "agys_home": p.home,
        "gemini_home": p.gemini_home,
        "exports_dir": p.exports,
        "encryption": "off" if p.no_encrypt else ("dpapi" if IS_WIN else "shake256+hmac"),
        "agy_binary": agy_binary(),
        "agy_version": agy_version(),
        "credential_store": store.describe(),
        "credential_present": live is not None,
        "credential_bytes": len(live) if live else 0,
        "credential_identity": live_ident,
        "credential_matches": matched,
        "google_accounts_active": (_read_ga() or {}).get("active"),
        "vault": {"accounts": len(v["accounts"]), "current": v.get("current"),
                  "layout_fingerprint": (v.get("layout") or {}).get("fingerprint")},        "layout": layout,
        "profiles": profiles,
        "pending_transaction": os.path.isfile(p.pending),
        "running_processes": None if procs is None else [x.__dict__ for x in procs],
        "ide_state_exists": os.path.isfile(ide_state_path()),
        "warnings": warnings,
    }


def _read_ga():
    try:
        with open(paths().ga, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return None


def render(d):
    lines = [f"agys v{d['version']} 诊断"]
    lines.append(f"  平台: {d['platform']}  Python: {d['python']}")
    lines.append(f"  agys 目录: {d['agys_home']}")
    lines.append(f"  gemini 目录: {d['gemini_home']}")
    lines.append(f"  本地加密: {d['encryption']}")
    lines.append(f"  agy 可执行文件: {d['agy_binary'] or '未找到!'}  (版本 {d['agy_version']})")
    lines.append(f"  凭据库: {d['credential_store']}")
    if d["credential_present"]:
        lines.append(f"    -> 有活跃凭据，{d['credential_bytes']} 字节，"
                     f"身份 {d['credential_identity']}，"
                     f"{('匹配 ' + d['credential_matches']) if d['credential_matches'] else '未纳管'}")
    else:
        lines.append("    -> 无活跃凭据（未登录）")
    lines.append(f"  google_accounts.json active: {d['google_accounts_active'] or '-'}")
    lines.append(f"  vault: {d['vault']['accounts']} 个帐号，当前 = {d['vault']['current'] or '无'}，"
                 f"布局指纹 = {d['vault']['layout_fingerprint'] or '未记录'}")
    for pr in d["profiles"]:
        lines.append(f"    [{'ok' if pr['ok'] else '坏'}] {pr['id']} "
                     f"({pr.get('identity') or '-'}) {pr.get('bytes', 0)} 字节"
                     + (f"  token {pr['token_expiry']}" if pr.get("token_expiry") else "")
                     + (f"  {pr['error']}" if pr.get("error") else ""))
    rp = d["running_processes"]
    lines.append("  运行中 agy 进程: " +
                 ("无法检测" if rp is None else
                  ("无" if not rp else ", ".join(f"{x['name']}(pid={x['pid']})" for x in rp))))
    lines.append(f"  IDE 状态库存在: {d['ide_state_exists']}")
    if d["pending_transaction"]:
        lines.append("  未完成事务: 有")
    for w in d["warnings"]:
        lines.append(f"  ! {w}")
    lines.append(f"  安全提示: {d['agys_home']} 内含本地登录凭据，请勿放入同步盘；"
                 f"导出文件在 {d['exports_dir']}（明文）")
    return "\n".join(lines)
