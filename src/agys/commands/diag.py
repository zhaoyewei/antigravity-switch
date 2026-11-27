"""诊断类命令：doctor / layout / log / version / update / check / stats / watch。"""
from __future__ import annotations

import os
import subprocess
import tempfile
import time

from .. import (APP, __version__, audit, doctor, installer, journal, layout,
                proxy, quota)
from ..common import AgysError, pad
from ..config import paths
from ..crypto import secure_dir
from ..vault import load_profile, migrate_profiles, save_vault


# ---------------------------------------------------------------- doctor

def _doctor_fix(rep, store, v):
    """修复常见问题：迁移明文 profile、回滚事务、修复索引、收紧权限。"""
    notes = []
    n = migrate_profiles()
    if n:
        notes.append(f"迁移 {n} 个明文 profile 为加密格式")
    if journal.recover(store):
        notes.append("清理了未完成的事务")
    added, removed = 0, 0
    for acc in list(v["accounts"]):
        try:
            load_profile(acc)
        except Exception:
            del v["accounts"][acc]
            removed += 1
            if v.get("current") == acc:
                v["current"] = None
    prof_dir = paths().profiles
    if os.path.isdir(prof_dir):
        for acc in os.listdir(prof_dir):
            if acc in v["accounts"] or not os.path.isfile(
                    os.path.join(prof_dir, acc, "profile.json")):
                continue
            try:
                prof = load_profile(acc)
                v["accounts"][acc] = {
                    "id": acc, "email": prof.get("email") or "",
                    "aliases": prof.get("aliases") or [],
                    "tags": prof.get("tags") or [],
                    "identity": prof.get("identity") or ""}
                added += 1
            except Exception:
                continue
    if added or removed:
        notes.append(f"vault 索引修复：补入 {added}、移除 {removed}")
        save_vault(v)
    secure_dir(paths().home)
    notes.append("已确认目录权限")
    rep.set(fixes=notes)
    for x in notes:
        rep.msg(f"  - {x}")


def cmd_doctor(args, rep, store, v):
    d = doctor.collect(store)
    rep.set(**d)
    rep.msg(doctor.render(d))
    if getattr(args, "fix", False):
        rep.msg(f"{APP}: 自动修复：")
        _doctor_fix(rep, store, v)


# ---------------------------------------------------------------- layout

def cmd_layout(args, rep, store, v):
    cur = layout.probe(store)
    cached = v.get("layout") or {}
    rep.set(current=cur, cached=cached)
    rep.msg(f"{APP}: 存储布局探测")
    for k in ("platform", "backend", "cred_target", "ga_path", "token_path",
              "agy_version", "ide_state_path", "fingerprint", "has_credential",
              "ga_exists", "token_exists", "ide_state_exists"):
        old = layout._cached_value(cached, k) if cached else None
        mark = "" if old in (None, cur.get(k)) else f"   (缓存: {old})"
        rep.msg(f"  {k:<18} {cur.get(k)}{mark}")
    ov = cur.get("overrides") or {}
    rep.msg("  自动适配覆盖     " + (", ".join(f"{k}={x}" for k, x in ov.items()) or "无"))
    if getattr(args, "discover", False) or getattr(args, "adopt", False):
        cands = layout.discover(store)
        rep.msg(f"  候选布局 {len(cands)} 个（只读探测）")
        for c in cands:
            mark = " <- 当前" if c["fingerprint"] == cur["fingerprint"] else ""
            rep.msg(f"    [{c['fingerprint']}] cred={c['cred_target']}  "
                    f"ga={'有' if c['ga_exists'] else '无'}  "
                    f"token={'有' if c['token_exists'] else '无'}  "
                    f"凭据={'有' if c['has_credential'] else '无'}{mark}")
    if getattr(args, "adopt", False):
        ok, msg = layout.adopt_best(v, store)
        if ok:
            rep.msg(f"{APP}: {msg}")
        else:
            cur = layout.adopt_current(v, store)
            rep.msg(f"{APP}: 未找到更合适的候选布局，已把当前布局记为基准 "
                    f"{cur['fingerprint']}")


# ---------------------------------------------------------------- log / stats / watch

def cmd_log(args, rep, store, v):
    rows = audit.read(args.limit)
    rep.set(entries=rows)
    for r in rows:
        rep.msg(f"{r['ts']}  {r['action']:<8} {r.get('from') or '-'} -> "
                f"{r.get('to') or '-'}  {r['result']}"
                + (f"  {r['detail']}" if r.get("detail") else ""))


def cmd_stats(args, rep, store, v):
    """各帐号使用统计：切换次数 / 失败次数 / 最后切换时间（来自审计日志，纯只读）。"""
    stats = {}

    def entry(acc):
        return stats.setdefault(acc, {"id": acc, "switches": 0, "failures": 0,
                                      "last_switch": "", "added": ""})

    for r in audit.read(limit=10 ** 6):
        action = r.get("action")
        to = r.get("to")
        if action == "add" and to:
            e = entry(to)
            e["added"] = e["added"] or r.get("ts") or ""
        elif action == "switch" and to:
            e = entry(to)
            if r.get("result") == "ok":
                e["switches"] += 1
                e["last_switch"] = r.get("ts") or ""
            else:
                e["failures"] += 1

    total = sum(e["switches"] for e in stats.values())
    out = []
    for acc in sorted(v["accounts"]):
        e = stats.pop(acc, None) or {"id": acc, "switches": 0, "failures": 0,
                                     "last_switch": "", "added": ""}
        meta = v["accounts"][acc]
        e.update({"email": meta.get("email") or "", "tags": meta.get("tags") or [],
                  "current": v.get("current") == acc, "deleted": False})
        out.append(e)
    for acc in sorted(stats):          # 日志里有、vault 里已删除的帐号
        e = stats[acc]
        e.update({"email": "", "tags": [], "current": False, "deleted": True})
        out.append(e)
    rep.set(accounts=out, total_switches=total)
    if not out:
        rep.msg("还没有任何帐号。用 agys add 添加第一个。")
        return
    rep.msg(f"{APP}: 帐号使用统计（数据来自审计日志）")
    rep.msg(f"  {'':2} {pad('ID', 18)} {pad('切换', 6)} {pad('失败', 6)} "
            f"{pad('最后切换', 20)} 备注")
    for e in out:
        mark = "*" if e["current"] else " "
        note = []
        if e.get("deleted"):
            note.append("已删除")
        if e.get("tags"):
            note.append(",".join(e["tags"]))
        if e.get("added"):
            note.append(f"添加于 {str(e['added'])[:10]}")
        rep.msg(f"  {mark:2} {pad(e['id'], 18)} {pad(e['switches'], 6)} "
                f"{pad(e['failures'], 6)} {pad(e['last_switch'] or '-', 20)} "
                f"{' '.join(note)}")
    rep.msg(f"  合计 {total} 次成功切换。注：统计只覆盖审计日志保留的部分，"
            "更早的历史不回溯。")


def cmd_watch(args, rep, store, v):
    """持续监控帐号额度：状态有变、当前帐号将耗尽时提醒（含终端响铃）。

    只读探测 + 额度缓存，不碰凭据。`--once` 单轮模式适合 cron / 计划任务。
    """
    if not v["accounts"]:
        raise AgysError("还没有任何帐号。用 agys add 添加第一个。")
    interval = max(30, int(getattr(args, "interval", 300)))
    low = min(1.0, max(0.0, float(getattr(args, "low", 0.1))))
    once = bool(getattr(args, "once", False))
    if rep.as_json and not once:
        raise AgysError("watch 持续模式不支持 --json（每轮都输出没有意义）；"
                        "单轮监控用 agys watch --once --json")
    rep.set(interval=interval, low=low, once=once)
    rep.msg(f"{APP}: 开始监控 {len(v['accounts'])} 个帐号"
            f"（每 {interval} 秒探测一次，Ctrl+C 停止；额度阈值 {low * 100:.0f}%）")
    prev = {}
    alerts = 0
    try:
        while True:
            reports = quota.snapshot(v)
            alerts += _watch_cycle(reports, v, low, prev, rep)
            rep.set(last=reports, alerts=alerts)
            if once:
                break
            time.sleep(interval)
    except KeyboardInterrupt:
        pass
    rep.msg(f"{APP}: 已停止监控（本次共 {alerts} 次提醒）")


def _watch_cycle(reports, v, low, prev, rep):
    """一轮探测：状态没变就不刷屏；异常与低额度提醒计入返回值。"""
    alerts = 0
    cur = v.get("current")
    stamp = time.strftime("%H:%M:%S")
    for r in reports:
        rid, state = r["id"], r.get("state")
        rem = r.get("remaining")
        sig = (state, rem if isinstance(rem, (int, float)) else None)
        old = prev.get(rid)
        prev[rid] = sig
        if old == sig:
            continue
        if state == "exhausted":
            reset = quota.fmt_reset(r.get("reset")) if r.get("reset") else ""
            extra = f"（{reset} 重置）" if reset else ""
            rep.warn(f"[{stamp}] 帐号 '{rid}' 额度已用尽{extra}"
                     + ("；这是当前帐号，运行 agys 自动换号" if rid == cur else ""))
            alerts += 1
        elif state == "auth":
            rep.warn(f"[{stamp}] 帐号 '{rid}' 需要重新登录"
                     f"（agys remove '{rid}' 后 agys add 重登）")
            alerts += 1
        elif state == "error":
            rep.warn(f"[{stamp}] 帐号 '{rid}' 探测失败：{(r.get('detail') or '')[:60]}")
            alerts += 1
        elif cur == rid and isinstance(rem, (int, float)) and rem <= low:
            rep.warn(f"[{stamp}] 当前帐号 '{rid}' 额度仅剩 {rem * 100:.0f}%"
                     f"（低于 {low * 100:.0f}% 阈值），建议准备 agys 换号")
            alerts += 1
        else:
            rep.msg(f"[{stamp}] '{rid}' {quota.describe(r)}")
    if alerts:
        rep.msg("\a")          # 终端响铃
    return alerts


def cmd_version(args, rep, store, v):
    rep.set(version=__version__)
    rep.msg(f"{APP} {__version__}")


# ---------------------------------------------------------------- update / check

def _release_owner():
    return os.environ.get("AGYS_GITHUB_OWNER", "zhaoyewei")


def _raw_url(path):
    return f"https://raw.githubusercontent.com/{_release_owner()}/antigravity-switch/main/{path}"


def _latest_version():
    """从仓库读 __version__；网络不可用返回 None。"""
    try:
        with proxy.urlopen(_raw_url("src/agys/__init__.py"), timeout=10) as r:
            text = r.read().decode("utf-8")
        return text.split('__version__ = "')[1].split('"')[0]
    except Exception:
        return None


def cmd_update(args, rep, store, v):
    if args.check:
        latest = _latest_version()
        if latest is None:
            raise AgysError("无法查询最新版本（离线或网络受限）")
        rep.msg(f"当前 {__version__}，仓库最新 {latest}")
        rep.set(current=__version__, latest=latest)
        return
    # 二进制安装的 Windows 用户没有 bash / Python，改用 PowerShell 安装脚本；
    # 其余情况沿用 install.sh（它本身会优先下载新二进制）。
    mode = installer.read_mode()
    script = installer.update_script(mode)
    url = (os.environ.get("AGYS_INSTALL_URL")
           or installer.installer_url(script, owner=_release_owner()))
    try:
        with proxy.urlopen(url, timeout=30) as r:
            script_body = r.read()
    except Exception as e:
        raise AgysError(f"下载安装脚本失败：{e}")
    is_ps = script.endswith(".ps1")
    fd, tmp = tempfile.mkstemp(prefix="agys-install-",
                               suffix=".ps1" if is_ps else ".sh")
    with os.fdopen(fd, "wb") as f:
        f.write(script_body)
    cmd = (["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", tmp]
           if is_ps else ["bash", tmp])
    try:
        rc = subprocess.call(cmd, env=proxy.child_env())
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    if rc != 0:
        raise AgysError(f"安装脚本返回 {rc}")
    rep.msg(f"{APP}: 已重新安装（{mode or 'source'} / {script}），"
            "请运行 agys version 确认版本")
    rep.set(updated=True, mode=mode or "source", installer=script)


def cmd_check(args, rep, store, v):
    latest = _latest_version()
    if latest is None:
        rep.warn("无法查询最新版本（离线或网络受限）")
    d = doctor.collect(store)
    rep.set(current=__version__, latest=latest,
            issues=len(d["warnings"]), warnings=d["warnings"])
    rep.msg(f"{APP} {__version__}"
            + (f" → 仓库最新 {latest}" if latest else "（版本检查跳过）"))
    rep.msg(f"自检：{len(d['warnings'])} 条提示；详细报告用 agys doctor")

