"""agys 命令行入口。"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time

from . import (__version__, audit, doctor, expimp, history, identity, journal,
               layout, process, tui)
from . import APP, agy_install, extra, proxy
from .common import AgysError, Reporter, SwitchLock, confirm, read_ga, write_ga
from .config import agy_argv, paths
from .credentials import CredentialError, get_store
from .crypto import CryptoError, secure_dir
from .vault import (
    delete_profile_dir, email_slug, find_by_identity, load_profile, load_vault,
    migrate_profiles, profile_path, resolve, save_profile, save_vault, slugify,
)


def _guard_flags(sp):
    g = sp.add_mutually_exclusive_group()
    g.add_argument("--no-guard", action="store_true",
                   help="不检测/不关闭运行中的 agy 进程（风险自负）")
    g.add_argument("--close-all", action="store_true",
                   help="自动关闭运行中的 agy 进程后再切换，切换完尽力重开")
    sp.add_argument("--yes", action="store_true", help="跳过交互确认（配合 --close-all / remove）")
    sp.add_argument("--allow-layout-change", action="store_true",
                    help="接受 agy 存储布局变化并更新指纹")


def ensure_ready(args, rep, store, v, strict=True):
    # 需要 agy 的命令自动检测/安装；刚装完时布局指纹会变化，需要放行一次
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
    allow = (getattr(args, "allow_layout_change", False) or installed)
    ok, msg = layout.verify(v, store, allow_change=allow)
    if not ok:
        if strict:
            raise AgysError(msg)
        rep.warn(msg.splitlines()[0] + "（本次为只读命令，继续执行）")
    elif msg:
        rep.msg(f"{APP}: {msg}")


def guard_processes(args, rep):
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


def verify_after_switch(store, prof, rep):
    """切换后读回验证，杜绝'假成功'。"""
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


def switch_to(acc_id, args, rep, store, v):
    guard_processes(args, rep)
    before = store.get()
    before_ga = read_ga()
    before_current = v.get("current")

    # 回收活跃凭据（用稳定 identity，不再靠邮箱字符串猜测）
    if before is not None:
        ident = identity.extract(before, before_ga)
        matched = find_by_identity(ident, v)
        if matched:
            meta = dict(v["accounts"][matched])
            save_profile(matched, before, before_ga, meta)
            if v.get("current") != matched:
                v["current"] = matched
                save_vault(v)
        else:
            em = identity.email_of(ident)
            adopt = email_slug(em) or slugify(identity.short(ident))
            save_profile(adopt, before, before_ga, {"email": em})
            v["accounts"][adopt] = {"id": adopt, "email": em, "aliases": [],
                                    "identity": ident}
            v["current"] = adopt
            save_vault(v)
            rep.msg(f"{APP}: 检测到未纳管的当前登录，已保存为帐号 '{adopt}'")

    prof = load_profile(acc_id)
    after = prof["blob"]
    after_ga = prof.get("google_accounts") or {"active": identity.email_of(
        prof.get("identity") or ""), "old": []}
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
    if layout.ide_state_path and os.path.isfile(layout.ide_state_path()):
        rep.msg(f"{APP}: 提示：Antigravity IDE 与 CLI 共享凭据，但窗口可能仍显示旧邮箱，"
                f"请执行 Developer: Reload Window 重载")
    reopened = process.reopen_previous()
    if reopened:
        rep.msg(f"{APP}: {reopened}")
    rep.set(current=acc_id, email=prof.get("email") or "")


# ---------------------------------------------------------------- 命令

def cmd_add(args, rep, store, v):
    with SwitchLock():
        guard_processes(args, rep)
        live = store.get()
        ga = read_ga()
        if live is not None:
            ident = identity.extract(live, ga)
            matched = find_by_identity(ident, v)
            if matched:
                save_profile(matched, live, ga, dict(v["accounts"][matched]))
                rep.msg(f"{APP}: 已把当前登录（'{matched}'）的最新 token 存回库中。")
            else:
                em = identity.email_of(ident)
                adopt = email_slug(em) or slugify(identity.short(ident))
                save_profile(adopt, live, ga, {"email": em})
                v["accounts"][adopt] = {"id": adopt, "email": em, "aliases": [],
                                        "identity": ident}
                save_vault(v)
                rep.msg(f"{APP}: 首次使用，已把当前登录保存为帐号 '{adopt}'")
        store.delete()
        b = agy_argv()
        if not b:
            raise AgysError("找不到 agy 可执行文件（可用 AGYS_AGY_BIN 指定）")
        rep.msg(f"{APP}: 即将启动 agy 登录流程，请在浏览器中完成 Google 登录，"
                f"登录完成后退出 agy（Ctrl+C 或 /quit）。")
        try:
            subprocess.call(b, env=proxy.child_env())
        except KeyboardInterrupt:
            pass
        new = store.get()
        if new is None:
            if live is not None:
                store.set(live)
            raise AgysError("未检测到新登录（凭据条目仍为空），已恢复原帐号凭据")
        new_ga = read_ga()
        new_ident = identity.extract(new, new_ga)
        if live is not None and new_ident == identity.extract(live, ga):
            m = find_by_identity(new_ident, v) or email_slug(identity.email_of(new_ident))
            save_profile(m, new, new_ga, dict(v["accounts"].get(m, {})))
            v["accounts"].setdefault(m, {})["identity"] = new_ident
            v["current"] = m
            save_vault(v)
            rep.msg(f"{APP}: 登录的还是同一帐号，已刷新其 token。")
            rep.set(current=m)
            return
        em = identity.email_of(new_ident)
        acc_id = slugify(args.name or em or identity.short(new_ident))
        if acc_id in v["accounts"]:
            raise AgysError(f"帐号 id '{acc_id}' 已存在，换一个名字或先 remove")
        meta = {"email": em, "aliases": args.alias or [], "identity": new_ident}
        save_profile(acc_id, new, new_ga, meta)
        v["accounts"][acc_id] = {"id": acc_id, "email": em,
                                 "aliases": args.alias or [], "identity": new_ident}
        v["current"] = acc_id
        save_vault(v)
        audit.log("add", to_id=acc_id, result="ok")
        rep.msg(f"{APP}: 已添加并切换到新帐号 '{acc_id}'（{em or new_ident}）")
        rep.set(current=acc_id, email=em)


def cmd_list(args, rep, store, v):
    rows = []
    cur = v.get("current")
    for acc, m in sorted(v["accounts"].items()):
        rows.append({"id": acc, "email": m.get("email") or "",
                     "aliases": m.get("aliases") or [],
                     "identity": m.get("identity") or "",
                     "current": acc == cur})
    rep.set(accounts=rows, current=cur)
    if not rows:
        rep.msg("还没有任何帐号。用 agys add 添加第一个（会自动保存当前登录）。")
        return
    w = max([len(r["email"]) for r in rows] + [5])
    rep.msg(f"{'*':<2} {'ID':<24} {'EMAIL':<{w}} ALIASES")
    for r in rows:
        rep.msg(f"{'*' if r['current'] else ' ':<2} {r['id']:<24} "
                f"{(r['email'] or '-'):<{w}} {','.join(r['aliases'])}")
    rep.msg(f"\n共 {len(rows)} 个帐号；* = 当前帐号。")


def cmd_current(args, rep, store, v):
    live = store.get()
    ga = read_ga()
    ident = identity.extract(live, ga) if live else None
    matched = find_by_identity(ident, v) if ident else None
    cur = v.get("current")
    consistent = (cur == matched) if live else (cur is None)
    rep.set(current=cur, active_identity=ident, active_matches=matched,
            consistent=consistent, google_accounts_active=(ga or {}).get("active"))
    rep.msg(f"当前帐号（vault）: {cur or '无'}")
    rep.msg(f"活跃凭据身份: {ident or '无'}"
            + (f"（匹配帐号 '{matched}'）" if matched else "（未纳管）" if ident else ""))
    rep.msg(f"活跃邮箱（google_accounts.json）: {(ga or {}).get('active') or '-'}")
    if not consistent and live:
        rep.warn("vault 记录的当前帐号与活跃凭据不一致，建议 agys use 重新切换")


def _pick_account(args, rep, store, v, title="agys 帐号切换"):
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


def cmd_use(args, rep, store, v):
    name = args.name
    # 非交互 / --json 场景下，省略帐号时回落到默认帐号
    if not name and (not sys.stdin.isatty() or rep.as_json) and v.get("default"):
        name = v["default"]
    if not name:
        name = _pick_account(args, rep, store, v)
    acc_id = resolve(name, v)
    with SwitchLock():
        switch_to(acc_id, args, rep, store, v)


def cmd_tui(args, rep, store, v):
    name = _pick_account(args, rep, store, v, title="agys 帐号切换（Enter 确认）")
    acc_id = resolve(name, v)
    with SwitchLock():
        switch_to(acc_id, args, rep, store, v)


def cmd_as(args, rep, store, v):
    tail = args.args_cmd or []
    if tail and tail[0] == "--":
        tail = tail[1:]
    if not args.name:
        raise AgysError("用法：agys as <帐号> [--] [agy 的参数...]")
    acc_id = resolve(args.name, v)
    need = True
    live = store.get()
    if v.get("current") == acc_id and live is not None:
        try:
            need = identity.extract(live, read_ga()) != load_profile(acc_id).get("identity")
        except (KeyError, CryptoError):
            pass
    if need:
        with SwitchLock():
            switch_to(acc_id, args, rep, store, v)
    else:
        rep.msg(f"{APP}: '{acc_id}' 已是当前帐号，直接启动 agy。")
        rep.set(current=acc_id)
    cmd = agy_argv(tail)
    if not cmd:
        raise AgysError("找不到 agy 可执行文件（可用 AGYS_AGY_BIN 指定）")
    rep.done()
    rc = subprocess.call(cmd, env=proxy.child_env())
    sys.exit(rc)


def cmd_remove(args, rep, store, v):
    acc_id = resolve(args.name, v)
    with SwitchLock():
        if not confirm(f"确认删除帐号 '{acc_id}'？", args.yes):
            raise AgysError("已取消")
        was_current = v.get("current") == acc_id
        v["accounts"].pop(acc_id, None)
        if was_current:
            v["current"] = None
            store.delete()
            write_ga({"active": "", "old": []})
        save_vault(v)
        delete_profile_dir(acc_id)
        audit.log("remove", from_id=acc_id, result="ok")
        rep.msg(f"{APP}: 已删除帐号 '{acc_id}'"
                + ("并清除活跃凭据（相当于登出）" if was_current else ""))
        rep.set(removed=acc_id, logged_out=was_current)


def cmd_alias(args, rep, store, v):
    acc_id = resolve(args.name, v)
    with SwitchLock():
        meta = v["accounts"][acc_id]
        aliases = list(meta.get("aliases") or [])
        if args.remove:
            aliases = [a for a in aliases if a not in args.aliases]
        else:
            for a in args.aliases:
                for other, om in v["accounts"].items():
                    other_aliases = [x.lower() for x in (om.get("aliases") or [])]
                    if other != acc_id and (a.lower() == other.lower()
                                            or a.lower() in other_aliases):
                        raise AgysError(f"别名 '{a}' 与帐号 '{other}' 冲突")
                if a not in aliases:
                    aliases.append(a)
        meta["aliases"] = aliases
        save_vault(v)
        prof = load_profile(acc_id)
        save_profile(acc_id, prof["blob"], prof.get("google_accounts"),
                     {**prof, "aliases": aliases})
        rep.msg(f"{APP}: 帐号 '{acc_id}' 的别名：{', '.join(aliases) or '（无）'}")
        rep.set(id=acc_id, aliases=aliases)


def cmd_rename(args, rep, store, v):
    old = resolve(args.name, v)
    new = slugify(args.new)
    with SwitchLock():
        if new == old:
            raise AgysError("新 id 与旧 id 相同")
        if new in v["accounts"]:
            raise AgysError(f"帐号 '{new}' 已存在")
        os.makedirs(os.path.dirname(profile_path(new)), exist_ok=True)
        os.replace(profile_path(old), profile_path(new))
        delete_profile_dir(old)
        v["accounts"][new] = v["accounts"].pop(old)
        if v.get("current") == old:
            v["current"] = new
        save_vault(v)
        audit.log("rename", from_id=old, to_id=new, result="ok")
        rep.msg(f"{APP}: 已把 '{old}' 重命名为 '{new}'")
        rep.set(old=old, new=new)


def cmd_export(args, rep, store, v):
    if not v["accounts"]:
        raise AgysError("没有任何帐号可导出")
    path = args.path or expimp.default_path()
    out = expimp.write_export(path, v)
    rep.msg(f"{APP}: 已导出 {len(out['accounts'])} 个帐号到 {path}")
    rep.msg(f"{APP}: 注意：文件内含明文登录凭据，请妥善保管、迁移完成后删除。")
    rep.msg(f"{APP}: {expimp.NOTE}")
    rep.set(path=path, count=len(out["accounts"]), checksum=out["checksum"])


def _unique_acc_id(base, accounts):
    """rename 策略下找一个不冲突的 id：alice -> alice-2 -> alice-3 ..."""
    if base not in accounts:
        return base
    n = 2
    while f"{base}-{n}" in accounts:
        n += 1
    return f"{base}-{n}"


def _ask_conflict(acc_id, incoming, v, args):
    if getattr(args, "yes", False):
        return True
    if not sys.stdin.isatty():
        raise AgysError(
            f"帐号 '{acc_id}' 已存在，而 --on-conflict ask 在非交互终端下无法提问。"
            "改用 skip / overwrite / rename，或加 --yes 表示全部覆盖。")
    cur = v["accounts"][acc_id]
    answer = input(f"帐号 '{acc_id}' 已存在（现有 {cur.get('email') or '-'} → "
                   f"导入 {incoming.get('email') or '-'}），覆盖？[y/N] ")
    return answer.strip().lower() in ("y", "yes")


def cmd_import(args, rep, store, v):
    accounts, warns = expimp.read_import(args.path, verify=not args.no_verify)
    policy = getattr(args, "on_conflict", "overwrite")
    with SwitchLock():
        added, updated, skipped, renamed = [], [], [], []
        for a in accounts:
            acc_id = slugify(a.get("id") or "")
            if not acc_id:
                continue
            blob = expimp.account_blob(a)
            ga = a.get("google_accounts")
            ident = a.get("identity") or identity.extract(blob, ga)
            meta = {"email": a.get("email") or identity.email_of(ident),
                    "aliases": a.get("aliases") or [], "identity": ident,
                    "created": a.get("created") or ""}
            existed = acc_id in v["accounts"]
            target = acc_id
            if existed:
                if policy == "skip":
                    skipped.append(acc_id)
                    continue
                if policy == "ask" and not _ask_conflict(acc_id, a, v, args):
                    skipped.append(acc_id)
                    continue
                if policy == "rename":
                    target = _unique_acc_id(acc_id, v["accounts"])
            save_profile(target, blob, ga, meta)
            v["accounts"][target] = {"id": target, **meta}
            if not existed:
                added.append(target)
            elif target == acc_id:
                updated.append(acc_id)
            else:
                renamed.append(f"{acc_id}->{target}")
        save_vault(v)
        audit.log("import", result="ok",
                  detail=f"{len(added)} new, {len(updated)} updated, "
                         f"{len(skipped)} skipped, {len(renamed)} renamed ({policy})")
        for w in warns:
            rep.warn(w)
        parts = [f"新导入 {len(added)} 个", f"更新 {len(updated)} 个"]
        if skipped:
            parts.append(f"跳过 {len(skipped)} 个")
        if renamed:
            parts.append("重命名 " + ", ".join(renamed))
        rep.msg(f"{APP}：" + "、".join(parts) + "；导入不会自动切换，用 agys use <id> 切换")
        rep.set(added=added, updated=updated, skipped=skipped, renamed=renamed,
                on_conflict=policy)


def cmd_history(args, rep, store, v):
    """只读查看 agy 会话历史。历史本就跨帐号共享，这里不区分帐号。"""
    if not history.available():
        raise AgysError("没找到 agy 会话目录：" + history.base_dir()
                        + "\n先运行一次 agy，或用 AGYS_GEMINI_HOME 指定配置目录。")
    action = args.action or "list"
    orphans = getattr(args, "orphans", True)
    limit = args.limit

    if action == "show":
        if not args.target:
            raise AgysError("用法：agys history show <会话 id 前缀>")
        hits, row = history.find(args.target, include_orphans=orphans)
        if row is None:
            if hits:
                raise AgysError("匹配到多个会话，请给更长的前缀："
                                + ", ".join(h["id"] for h in hits[:8]))
            raise AgysError(f"没有找到会话 {args.target}")
        steps = history.read_steps(row["id"], limit=args.steps)
        rep.set(conversation=row, steps=steps)
        rep.msg(f"{APP}: {row['title'] or '(未命名会话)'}")
        rep.msg(f"  id         {row['id']}")
        rep.msg(f"  时间       {row['updated'] or '-'}    步数 {row['steps']}"
                + (f"    大小 {row['size'] // 1024} KB" if row.get("size") else ""))
        if row["workspace"]:
            rep.msg("  workspace  " + ", ".join(row["workspace"]))
        if row.get("status"):
            rep.msg(f"  状态       {row['status']}")
        if not steps:
            rep.msg("  （读不到步骤明细，会话文件可能已被清理）")
        shown = 0
        for st in steps:
            if st["excerpt"]:
                rep.msg(f"    [{st['idx']:>3}] {st['excerpt'][:100]}")
                shown += 1
        if steps and not shown:
            rep.msg("  （这个会话没有可读的文字内容）")
        return

    if action == "export":
        fmt = args.format
        suffix = ".md" if fmt == "md" else ".json"
        target = args.target or os.path.join(
            paths().exports, "history-" + time.strftime("%Y%m%d-%H%M%S") + suffix)
        if not os.path.splitext(target)[1]:
            target += suffix
        items = history.collect(search=args.search, workspace=args.workspace,
                                limit=None, include_orphans=orphans)
        payload = history.build_export(items, details=args.detail, max_steps=args.steps)
        secure_dir(os.path.dirname(target) or ".")
        if fmt == "md":
            body = history.render_markdown(payload)
        else:
            body = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        with open(target, "w", encoding="utf-8") as f:
            f.write(body)
        rep.set(path=target, count=payload["count"])
        rep.msg(f"{APP}: 已导出 {payload['count']} 个会话到 {target}")
        return

    search = args.search or (args.target if action == "search" else None)
    items = history.collect(search=search, workspace=args.workspace,
                            limit=limit, include_orphans=orphans)
    rep.set(count=len(items), conversations=items)
    if not items:
        rep.msg("没有匹配的会话。")
        return
    rep.msg(f"{APP}: {len(items)} 个会话（agy 历史不按帐号分区，所有帐号共用同一份）")
    for i in items:
        flag = "?" if i["source"] == "scan" else " "
        rep.msg(f" {flag} {i['updated'] or '-':<19} {i['steps']:>4}步  "
                f"{i['id'][:8]}  {(i['title'] or '(未命名会话)')[:46]}")
    if any(i["source"] == "scan" for i in items):
        rep.msg("  ? = 摘要库里没有记录，仅从会话文件推断（可能已被清理）")
    rep.msg("  详情：agys history show <id 前缀>；搜索：agys history --search 关键词")


def cmd_log(args, rep, store, v):
    rows = audit.read(args.limit)
    rep.set(entries=rows)
    for r in rows:
        rep.msg(f"{r['ts']}  {r['action']:<8} {r.get('from') or '-'} -> "
                f"{r.get('to') or '-'}  {r['result']}"
                + (f"  {r['detail']}" if r.get("detail") else ""))


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


def cmd_doctor(args, rep, store, v):
    d = doctor.collect(store)
    rep.set(**d)
    rep.msg(doctor.render(d))
    if getattr(args, "fix", False):
        rep.msg(f"{APP}: 自动修复：")
        extra.doctor_fix(rep, store, v)


def cmd_version(args, rep, store, v):
    rep.set(version=__version__)
    rep.msg(f"{APP} {__version__}")


def cmd_update(args, rep, store, v):
    owner = os.environ.get("AGYS_GITHUB_OWNER", "zhaoyewei")
    url = os.environ.get("AGYS_INSTALL_URL") or (
        f"https://raw.githubusercontent.com/{owner}/antigravity-switch/main/install.sh")
    if args.check:
        init = (f"https://raw.githubusercontent.com/{owner}/antigravity-switch/main/"
                "src/agys/__init__.py")
        try:
            with proxy.urlopen(init, timeout=15) as r:
                text = r.read().decode("utf-8")
            latest = text.split('__version__ = "')[1].split('"')[0]
        except Exception as e:
            raise AgysError(f"无法查询最新版本：{e}")
        rep.msg(f"当前 {__version__}，仓库最新 {latest}")
        rep.set(current=__version__, latest=latest)
        return
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


# ---------------------------------------------------------------- 参数解析

def _reorder_as_flags(argv):
    """把 as 命令后出现的 agys 自身 flags 提到帐号名之前，
    解决 argparse REMAINDER 吞掉 flag 的问题。'--' 之后一律透传给 agy。"""
    a = list(argv)
    idx = next((i for i, x in enumerate(a) if x in ("as", "run")), None)
    if idx is None:
        return a
    head, rest = a[:idx + 1], a[idx + 1:]
    known = {"--no-guard", "--close-all", "--yes",
             "--allow-layout-change", "--json"}
    flags, body, sep = [], [], False
    for t in rest:
        if t == "--" and not sep:
            sep = True
            body.append(t)
        elif not sep and t in known:
            flags.append(t)
        else:
            body.append(t)
    return head + flags + body


def build_parser():
    p = argparse.ArgumentParser(
        prog=APP, description="Antigravity (agy) 多帐号切换器",
        epilog="提示：as 命令的 agys flags 建议写在帐号名前；"
               "`--` 之后的参数全部透传给 agy。")
    p.add_argument("--json", action="store_true", help="以 JSON 输出（便于脚本集成）")
    p.add_argument("--version", action="version", version=f"{APP} {__version__}")
    sub = p.add_subparsers(dest="cmd")

    sp = sub.add_parser("add", help="添加帐号（先保存当前登录，再走 agy 登录流程）")
    sp.add_argument("name", nargs="?", help="帐号 id（缺省用登录邮箱局部名）")
    sp.add_argument("--alias", action="append", help="添加别名（可重复）")
    _guard_flags(sp)
    sp.set_defaults(func=cmd_add)

    sp = sub.add_parser("list", aliases=["ls"], help="列出所有帐号")
    sp.set_defaults(func=cmd_list)
    sub.add_parser("current", help="查看当前帐号与活跃凭据是否一致").set_defaults(func=cmd_current)

    sp = sub.add_parser("use", aliases=["switch"], help="切换帐号（id / 邮箱 / 别名 / 唯一前缀）")
    sp.add_argument("name", nargs="?", help="帐号；交互终端下省略会打开选择器")
    _guard_flags(sp)
    sp.set_defaults(func=cmd_use)

    sp = sub.add_parser("tui", help="交互式选择帐号并切换（方向键 + 回车）")
    _guard_flags(sp)
    sp.set_defaults(func=cmd_tui)

    sp = sub.add_parser("as", aliases=["run"], help="切换并以该帐号启动 agy，后续参数透传")
    sp.add_argument("name", nargs="?", help="帐号")
    sp.add_argument("args_cmd", nargs=argparse.REMAINDER, help="透传给 agy 的参数")
    _guard_flags(sp)
    sp.set_defaults(func=cmd_as)

    sp = sub.add_parser("remove", aliases=["rm"], help="删除帐号（删除当前帐号会同时登出）")
    sp.add_argument("name")
    sp.add_argument("--yes", action="store_true", help="跳过确认")
    sp.set_defaults(func=cmd_remove)

    sp = sub.add_parser("alias", help="设置别名")
    sp.add_argument("name")
    sp.add_argument("aliases", nargs="+")
    sp.add_argument("--remove", action="store_true", help="删除这些别名")
    sp.set_defaults(func=cmd_alias)

    sp = sub.add_parser("rename", help="重命名帐号 id")
    sp.add_argument("name")
    sp.add_argument("new")
    sp.set_defaults(func=cmd_rename)

    sp = sub.add_parser("export", help="导出所有帐号（明文，迁移用途）")
    sp.add_argument("path", nargs="?", help="输出路径（缺省 ~/.agy-accounts/exports/）")
    sp.set_defaults(func=cmd_export)

    sp = sub.add_parser("import", help="导入导出文件（不自动切换）")
    sp.add_argument("path")
    sp.add_argument("--no-verify", action="store_true", help="跳过校验和检查")
    sp.add_argument("--on-conflict", default="overwrite",
                    choices=("ask", "skip", "overwrite", "rename"),
                    help="id 已存在时的处理方式：ask 逐个询问 / skip 保留现有 / "
                         "overwrite 覆盖（默认）/ rename 换个 id 并存")
    sp.add_argument("--yes", action="store_true",
                    help="配合 --on-conflict ask：冲突时一律覆盖")
    sp.set_defaults(func=cmd_import)

    sp = sub.add_parser("log", help="查看切换审计日志")
    sp.add_argument("-n", "--limit", type=int, default=20)
    sp.set_defaults(func=cmd_log)

    sp = sub.add_parser("history", help="查看/搜索 agy 会话历史（所有帐号共享同一份）")
    sp.add_argument("action", nargs="?", default="list",
                    choices=("list", "show", "search", "export"))
    sp.add_argument("target", nargs="?",
                    help="show: 会话 id 前缀 / search: 关键词 / export: 输出路径")
    sp.add_argument("-n", "--limit", type=int, default=20)
    sp.add_argument("--search", help="按关键词过滤（标题 / preview / workspace / id）")
    sp.add_argument("--workspace", help="按 workspace 路径过滤")
    sp.add_argument("--no-orphans", dest="orphans", action="store_false",
                    help="不显示摘要库里没有记录的孤立会话")
    sp.add_argument("--steps", type=int, default=30, help="show 时最多列多少步")
    sp.add_argument("--detail", action="store_true", help="export 时附带步骤摘要")
    sp.add_argument("--format", default="json", choices=("json", "md"),
                    help="export 的格式")
    sp.set_defaults(func=cmd_history)

    sp = sub.add_parser("layout", help="显示 agy 存储布局；--discover 列出候选，--adopt 自动适配")
    sp.add_argument("--discover", action="store_true", help="列出候选布局（只读探测）")
    sp.add_argument("--adopt", action="store_true",
                    help="自动发现并采纳可用布局；无候选时把当前布局记为基准")
    sp.set_defaults(func=cmd_layout)

    sp = sub.add_parser("doctor", help="环境自检；--fix 自动修复常见问题")
    sp.add_argument("--fix", action="store_true",
                    help="迁移明文 profile / 回滚未完成事务 / 修复索引 / 收紧权限")
    sp.set_defaults(func=cmd_doctor)

    sub.add_parser("version", help="显示版本").set_defaults(func=cmd_version)

    sp = sub.add_parser("update", help="重新运行安装脚本升级 agys")
    sp.add_argument("--check", action="store_true", help="只检查最新版本")
    sp.set_defaults(func=cmd_update)

    # ---- 扩展命令（实现见 extra.py）----
    sub.add_parser("init", help="首次引导：检测/安装 agy 并收录当前登录").set_defaults(
        func=extra.cmd_init)
    sub.add_parser("status", help="一行状态概览（当前 / 活跃 / 进程 / 加密）").set_defaults(
        func=extra.cmd_status)
    sub.add_parser("whoami", help="输出当前活跃邮箱（脚本友好）").set_defaults(
        func=extra.cmd_whoami)
    sub.add_parser("logout", help="登出并清除活跃凭据，但保留所有帐号").set_defaults(
        func=extra.cmd_logout)
    sub.add_parser("ids", help="列出所有 id 与别名（供补全 / 脚本使用）").set_defaults(
        func=extra.cmd_ids)

    sp = sub.add_parser("info", help="查看帐号详情与 token 过期时间")
    sp.add_argument("name", nargs="?", help="帐号（缺省用当前帐号）")
    sp.set_defaults(func=extra.cmd_info)

    sp = sub.add_parser("default", help="查看 / 设置默认帐号")
    sp.add_argument("name", nargs="?", help="要设为默认的帐号；省略则查看")
    sp.set_defaults(func=extra.cmd_default)

    sp = sub.add_parser("completion", help="生成 shell 补全脚本")
    sp.add_argument("shell", choices=sorted(extra.COMPLETION))
    sp.set_defaults(func=extra.cmd_completion)

    sp = sub.add_parser("backup", help="备份整个 vault 为 tar.gz")
    sp.add_argument("path", nargs="?", help="输出路径（缺省 ~/.agy-accounts/backups/）")
    sp.set_defaults(func=extra.cmd_backup)

    sp = sub.add_parser("restore", help="从 tar.gz 备份恢复（覆盖当前数据）")
    sp.add_argument("path")
    sp.add_argument("--yes", action="store_true", help="跳过确认")
    sp.set_defaults(func=extra.cmd_restore)

    sub.add_parser("check", help="检查新版本并做快速自检").set_defaults(func=extra.cmd_check)

    sp = sub.add_parser("proxy", help="配置 agy 子进程使用的代理（不改系统代理）")
    psub = sp.add_subparsers(dest="proxy_cmd")
    psub.add_parser("show", help="查看当前代理配置与来源").set_defaults(func=extra.cmd_proxy)
    pset = psub.add_parser("set", help="设置代理，例如 http://127.0.0.1:7890")
    pset.add_argument("url", help="代理地址（http / https / socks5）")
    pset.add_argument("--no-proxy",
                      help="NO_PROXY 列表（逗号分隔），默认追加 localhost/127.0.0.1/::1")
    pset.set_defaults(func=extra.cmd_proxy)
    psub.add_parser("clear", help="清除代理配置").set_defaults(func=extra.cmd_proxy)
    ptest = psub.add_parser("test", help="测试代理连通性")
    ptest.add_argument("url", nargs="?", help="要测试的代理；缺省用当前配置")
    ptest.set_defaults(func=extra.cmd_proxy)
    sp.set_defaults(func=extra.cmd_proxy)

    sp = sub.add_parser("help", help="查看内置帮助主题")
    sp.add_argument("topic", nargs="?", choices=sorted(extra.TOPICS),
                    help="commands / workflows / troubleshooting / env / security")
    sp.set_defaults(func=extra.cmd_help)
    return p


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    argv = _reorder_as_flags(argv)
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    # 别名规范化：保证 strict 校验与 NEEDS_AGY 判断都基于主命令名
    aliases = {"ls": "list", "switch": "use", "run": "as", "rm": "remove"}
    args.cmd = aliases.get(args.cmd, args.cmd)
    rep = Reporter(args.json)
    try:
        v = load_vault()
        # 上次自动适配的布局必须先落到进程配置，之后才能构造凭据后端
        layout.apply_cached(v)
        store = get_store()
        strict = args.cmd in ("add", "use", "as", "tui")
        ensure_ready(args, rep, store, v, strict=strict)
        args.func(args, rep, store, v)
        rep.done()
        return 0
    except (AgysError, CredentialError, CryptoError, KeyError,
            ValueError, RuntimeError, OSError, AttributeError, TypeError) as e:
        msg = str(e)
        if args.json:
            print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False))
        else:
            print(f"{APP}: 错误：{msg}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print(f"\n{APP}: 已取消。", file=sys.stderr)
        return 130
