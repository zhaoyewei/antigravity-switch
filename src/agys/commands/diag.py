"""诊断类命令：doctor / layout / log / version / update / check。"""
from __future__ import annotations

import os
import subprocess
import tempfile

from .. import APP, __version__, audit, doctor, journal, layout, proxy
from ..common import AgysError
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


# ---------------------------------------------------------------- log / version

def cmd_log(args, rep, store, v):
    rows = audit.read(args.limit)
    rep.set(entries=rows)
    for r in rows:
        rep.msg(f"{r['ts']}  {r['action']:<8} {r.get('from') or '-'} -> "
                f"{r.get('to') or '-'}  {r['result']}"
                + (f"  {r['detail']}" if r.get("detail") else ""))


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
    url = os.environ.get("AGYS_INSTALL_URL") or _raw_url("install.sh")
    try:
        with proxy.urlopen(url, timeout=30) as r:
            script = r.read()
    except Exception as e:
        raise AgysError(f"下载安装脚本失败：{e}")
    fd, tmp = tempfile.mkstemp(prefix="agys-install-", suffix=".sh")
    with os.fdopen(fd, "wb") as f:
        f.write(script)
    try:
        rc = subprocess.call(["bash", tmp], env=proxy.child_env())
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    if rc != 0:
        raise AgysError(f"安装脚本返回 {rc}")
    rep.msg(f"{APP}: 已重新安装，请运行 agys version 确认版本")
    rep.set(updated=True)


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

