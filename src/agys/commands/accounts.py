"""帐号增删改查：add / list / current / remove / alias / rename / info / default / ids。"""
from __future__ import annotations

import datetime
import json
import os
import subprocess

from .. import APP, audit, identity, proxy
from ..common import AgysError, SwitchLock, confirm, read_ga, write_ga
from ..config import agy_argv
from ..runtime import guard_processes
from ..vault import (
    delete_profile_dir, email_slug, find_by_identity, load_profile, profile_path,
    resolve, save_profile, save_vault, slugify,
)


# ---------------------------------------------------------------- add

def cmd_add(args, rep, store, v):
    """保存当前登录 → 清凭据 → 让 agy 走一次浏览器登录 → 收录新帐号。"""
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


# ---------------------------------------------------------------- 查看

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


def cmd_ids(args, rep, store, v):
    ids = []
    for acc, meta in sorted(v["accounts"].items()):
        ids.append(acc)
        ids.extend(meta.get("aliases") or [])
    rep.set(ids=ids)
    for x in ids:
        rep.msg(x)


def _token_expiry(blob):
    """尽力从 token 里解析过期时间，返回 ISO 字符串或 None。"""
    try:
        data = json.loads(blob.decode("utf-8"))
    except Exception:
        return None

    def walk(o, depth=0):
        if depth > 6:
            return None
        if isinstance(o, dict):
            for k, val in o.items():
                if str(k).lower() in ("expiry", "expires_at", "expiry_date", "exp"):
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


def cmd_info(args, rep, store, v):
    name = args.name or v.get("current")
    if not name:
        raise AgysError("请指定帐号：agys info <帐号>（或先运行 agys add）")
    acc = resolve(name, v)
    prof = load_profile(acc)
    expiry = _token_expiry(prof["blob"])
    rep.set(id=acc, email=prof.get("email") or "", aliases=prof.get("aliases") or [],
            identity=prof.get("identity") or "", created=prof.get("created") or "",
            updated=prof.get("updated") or "", credential_bytes=len(prof["blob"]),
            token_expiry=expiry, is_default=v.get("default") == acc)
    rep.msg(f"帐号      {acc}")
    rep.msg(f"邮箱      {prof.get('email') or '-'}")
    rep.msg(f"身份      {prof.get('identity') or '-'}")
    rep.msg(f"别名      {', '.join(prof.get('aliases') or []) or '（无）'}")
    rep.msg(f"创建      {prof.get('created') or '-'}")
    rep.msg(f"更新      {prof.get('updated') or '-'}")
    rep.msg(f"凭据大小  {len(prof['blob'])} 字节")
    rep.msg(f"过期时间  {expiry or '未标注（由 agy 自动刷新）'}")
    rep.msg(f"默认帐号  {'是' if v.get('default') == acc else '否'}")


def cmd_default(args, rep, store, v):
    with SwitchLock():
        if args.name:
            acc = resolve(args.name, v)
            v["default"] = acc
            save_vault(v)
            rep.msg(f"{APP}: 默认帐号已设为 '{acc}'")
        rep.set(default=v.get("default"))
        if not args.name:
            rep.msg(f"默认帐号：{v.get('default') or '未设置'}")


# ---------------------------------------------------------------- 修改

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
