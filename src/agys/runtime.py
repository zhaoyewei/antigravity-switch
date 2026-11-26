"""命令运行时：所有会写凭据 / 启动进程的命令共用这套流程。

拆出来的原因：`ensure_ready` / `switch_to` 被十几条命令调用，之前和命令实现
混在一个 868 行的文件里。这里只放「流程」，不放任何一条具体命令。
"""
from __future__ import annotations

import os
import subprocess

from . import APP, agy_install, audit, identity, journal, layout, process, proxy, tui
from .common import AgysError, SwitchLock, confirm, read_ga, write_ga
from .config import agy_argv, paths
from .credentials import CredentialError
from .crypto import CryptoError, secure_dir
from .vault import (
    email_slug, find_by_identity, load_profile, migrate_profiles, resolve,
    save_profile, save_vault, slugify,
)


# ---------------------------------------------------------------- 启动前准备

def ensure_ready(args, rep, store, v, strict=True):
    """装好 agy、迁移旧格式、回滚未完成事务、校验存储布局。"""
    installed = False
    if args.cmd in agy_install.NEEDS_AGY:
        installed = agy_install.ensure(rep)
    secure_dir(paths().home)
    n = migrate_profiles()
    if n:
        rep.msg(f"{APP}: 已把 {n} 个 v0.1 明文帐号升级为加密存储。")
    notice = journal.recover(store)
    if notice:
        rep.warn(notice)
    # 只读/诊断命令永远可用：布局问题只拦截会写凭据的切换类命令
    allow = getattr(args, "allow_layout_change", False) or installed
    ok, msg = layout.verify(v, store, allow_change=allow)
    if not ok:
        if strict:
            raise AgysError(msg)
        rep.warn(msg.splitlines()[0] + "（本次为只读命令，继续执行）")
    elif msg:
        rep.msg(f"{APP}: {msg}")


def guard_processes(args, rep):
    """切换前挡住运行中的 agy，避免后台刷新把旧帐号写回去。"""
    procs = process.list_procs()
    if procs is None:
        rep.warn("无法检测 agy 进程（检测工具不可用），继续执行")
        return
    if not procs:
        return
    if getattr(args, "no_guard", False):
        rep.warn("检测到运行中的 agy 进程但已强制继续：" + process.describe(procs))
        return
    if getattr(args, "close_all", False):
        if not confirm("将关闭以下进程：" + process.describe(procs), args.yes):
            raise AgysError("已取消")
        n = process.close_all(procs)
        process.save_reopen(procs)
        rep.msg(f"{APP}: 已关闭 {n} 个进程，开始切换")
        return
    raise AgysError(
        "检测到正在运行的 Antigravity 进程：" + process.describe(procs) + "。\n"
        "后台 agy 会在 token 刷新时把旧帐号写回凭据库，导致切换被静默回退。\n"
        "可选：--close-all 自动关闭并切换（切换后尽力重开）、"
        "--no-guard 强制切换（风险自负），或先手动退出这些进程。")


# ---------------------------------------------------------------- 切换

def verify_after_switch(store, prof, rep):
    """切换后读回验证，杜绝「假成功」。"""
    back = store.get()
    ga = read_ga()
    if back is None:
        raise AgysError("切换后验证失败：凭据条目为空")
    ident = identity.extract(back, ga)
    expected = prof.get("identity")
    if back != prof["blob"]:
        raise AgysError("切换后验证失败：写回的凭据与目标帐号不一致")
    if expected and ident != expected:
        raise AgysError(f"切换后验证失败：活跃身份 {ident} != 目标 {expected}")
    rep.set(verified=True, active_identity=ident)
    return ident


def collect_live_credential(rep, store, v):
    """把当前活跃凭据回收进 vault（未纳管就自动收录）。"""
    live = store.get()
    ga = read_ga()
    if live is None:
        return
    ident = identity.extract(live, ga)
    matched = find_by_identity(ident, v)
    if matched:
        save_profile(matched, live, ga, dict(v["accounts"][matched]))
        if v.get("current") != matched:
            v["current"] = matched
            save_vault(v)
        return
    em = identity.email_of(ident)
    adopt = email_slug(em) or slugify(identity.short(ident))
    save_profile(adopt, live, ga, {"email": em})
    v["accounts"][adopt] = {"id": adopt, "email": em, "aliases": [], "identity": ident}
    v["current"] = adopt
    save_vault(v)
    rep.msg(f"{APP}: 检测到未纳管的当前登录，已保存为帐号 '{adopt}'")


def switch_to(acc_id, args, rep, store, v):
    """原子切换：回收 → 事务日志 → 写凭据与显示状态 → 读回验证 → 提交或回滚。"""
    guard_processes(args, rep)
    before = store.get()
    before_ga = read_ga()
    before_current = v.get("current")

    collect_live_credential(rep, store, v)

    prof = load_profile(acc_id)
    after = prof["blob"]
    after_ga = prof.get("google_accounts") or {
        "active": identity.email_of(prof.get("identity") or ""), "old": []}
    journal.begin(target=acc_id, before_cred=before, before_ga=before_ga,
                  before_current=before_current, after_cred=after,
                  after_ga=after_ga, after_current=acc_id)
    try:
        store.set(after)
        journal.set_phase("credential")
        write_ga(after_ga)
        journal.set_phase("google_accounts")
        v["current"] = acc_id
        v["accounts"].setdefault(acc_id, {})["identity"] = prof.get("identity") or ""
        save_vault(v)
        journal.set_phase("vault")
        verify_after_switch(store, prof, rep)
    except Exception as e:
        try:
            if before is None:
                store.delete()
            else:
                store.set(before)
            if before_ga is not None:
                write_ga(before_ga)
            v["current"] = before_current
            save_vault(v)
        except Exception as re_:
            rep.warn(f"回滚失败：{re_}（请运行 agys doctor 检查）")
        journal.finish()
        audit.log("switch", from_id=before_current, to_id=acc_id,
                  result="rolled-back", detail=str(e))
        raise AgysError(f"切换失败并已回滚：{e}")
    journal.finish()
    audit.log("switch", from_id=before_current, to_id=acc_id, result="ok")
    rep.msg(f"{APP}: 已切换到 '{acc_id}'（{prof.get('email') or prof.get('identity')}）"
            f"，读回验证通过")
    if os.path.isfile(layout.ide_state_path()):
        rep.msg(f"{APP}: 提示：Antigravity IDE 与 CLI 共享凭据，但窗口可能仍显示旧邮箱，"
                f"请执行 Developer: Reload Window 重载")
    reopened = process.reopen_previous()
    if reopened:
        rep.msg(f"{APP}: {reopened}")
    rep.set(current=acc_id, email=prof.get("email") or "")


def switch_if_needed(acc_id, args, rep, store, v):
    """已经是目标帐号且凭据没漂移就跳过切换（`as` / `auto` 用）。"""
    live = store.get()
    if v.get("current") == acc_id and live is not None:
        try:
            if identity.extract(live, read_ga()) == load_profile(acc_id).get("identity"):
                rep.msg(f"{APP}: '{acc_id}' 已是当前帐号，直接启动 agy。")
                rep.set(current=acc_id)
                return False
        except (KeyError, CryptoError, CredentialError):
            pass
    with SwitchLock():
        switch_to(acc_id, args, rep, store, v)
    return True


# ---------------------------------------------------------------- 启动 agy

def launch(tail=None, rep=None):
    """启动 agy 并把退出码带出去（`as` / `auto` 共用）。"""
    cmd = agy_argv(tail or [])
    if not cmd:
        raise AgysError("找不到 agy 可执行文件（可用 AGYS_AGY_BIN 指定）")
    if rep is not None:
        rep.done()
    return subprocess.call(cmd, env=proxy.child_env())


# ---------------------------------------------------------------- 交互选号

def pick_account(args, rep, store, v, title="agys 帐号切换"):
    """交互式选号。非 TTY 场景直接报错，不猜。"""
    if not v["accounts"]:
        raise AgysError("还没有任何帐号。用 agys add 添加第一个。")
    if rep.as_json or not tui.supported():
        raise AgysError("用法：agys use <帐号>（交互终端里可以省略帐号直接选）")
    try:
        active = layout.live_identity(store, read_ga())
    except (CredentialError, OSError):
        active = None
    try:
        chosen = tui.pick(v["accounts"], current=v.get("current"),
                          active=active, title=title)
    except RuntimeError as e:
        raise AgysError(str(e))
    if not chosen:
        raise AgysError("已取消")
    return chosen


def resolve_or_pick(args, rep, store, v, name, title="agys 帐号切换"):
    """把「用户给的字符串」或「省略时的交互选择」统一成帐号 id。

    交互选择只在真有终端时启用。注意 Windows 上 stdin 被重定向到 NUL 时
    `isatty()` 仍会返回 True（NUL 是字符设备），所以这里必须用
    `tui.supported()` 一并确认 stdout 也是终端；否则 `agys use` 在脚本里
    会被误判成交互场景，进而因为读不到按键而报错。
    """
    if name:
        return resolve(name, v)
    if not rep.as_json and tui.supported():
        return resolve(pick_account(args, rep, store, v, title=title), v)
    if v.get("default"):
        return resolve(v["default"], v)
    raise AgysError("用法：agys use <帐号>（交互终端里可以省略帐号直接选）")
