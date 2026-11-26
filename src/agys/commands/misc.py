"""零散命令：init / status / whoami / logout / completion / help。"""
from __future__ import annotations

from .. import APP, agy_install, audit, doctor, history, identity
from ..common import AgysError, SwitchLock, read_ga, write_ga
from ..helptext import COMPLETION, TOPICS
from ..vault import (
    email_slug, find_by_identity, save_profile, save_vault, slugify,
)


# ---------------------------------------------------------------- init

def cmd_init(args, rep, store, v):
    info = agy_install.describe()
    rep.set(agy=info)
    rep.msg(f"{APP}: agy = {info['location'] or '未安装'}")
    if not info["installed"]:
        rep.warn("agy 未安装（自动安装可能被 AGYS_NO_AUTO_INSTALL=1 关闭）。"
                 "可设置 AGYS_AGY_BIN 指向已有二进制，或查看 agys help troubleshooting")
    live = store.get()
    ga = read_ga()
    if live is None:
        rep.msg(f"{APP}: 当前尚未登录 agy。下一步：agys add（会打开浏览器登录）")
        rep.set(accounts=len(v["accounts"]), logged_in=False)
        return
    ident = identity.extract(live, ga)
    matched = find_by_identity(ident, v)
    if matched:
        rep.msg(f"{APP}: 当前登录已是纳管帐号 '{matched}'")
    else:
        em = identity.email_of(ident)
        acc = email_slug(em) or slugify(identity.short(ident))
        save_profile(acc, live, ga, {"email": em, "identity": ident})
        v["accounts"][acc] = {"id": acc, "email": em, "aliases": [], "identity": ident}
        v["current"] = acc
        save_vault(v)
        rep.msg(f"{APP}: 已把当前登录收录为帐号 '{acc}'（{em or ident}）")
    rep.msg(f"{APP}: 下一步：agys（自动选号启动）、agys add 加号、agys auto --status 看额度")
    rep.set(accounts=len(v["accounts"]), logged_in=True, identity=ident)


# ---------------------------------------------------------------- status

def cmd_status(args, rep, store, v):
    d = doctor.collect(store)
    procs = d["running_processes"]
    nproc = "未知" if procs is None else str(len(procs))
    consistent = "一致" if d["vault"]["current"] == d["credential_matches"] else "不一致"
    rep.msg(f"当前 {d['vault']['current'] or '无'} | 活跃 {d['credential_identity'] or '无'} "
            f"({consistent}) | 帐号 {d['vault']['accounts']} | 进程 {nproc} | "
            f"加密 {d['encryption']} | agy {d['agy_version']}")
    hist = history.overview()
    if hist:
        rep.msg(f"会话历史 {hist['total']} 个（所有帐号共享）"
                + (f"，其中 {hist['orphan']} 个孤立" if hist["orphan"] else "")
                + (f"，最近 {hist['latest']}" if hist["latest"] else ""))
    rep.set(current=d["vault"]["current"], active_identity=d["credential_identity"],
            consistent=consistent == "一致", accounts=d["vault"]["accounts"],
            running_processes=nproc, encryption=d["encryption"],
            agy_version=d["agy_version"], history=hist, warnings=d["warnings"])


def cmd_whoami(args, rep, store, v):
    live = store.get()
    ga = read_ga()
    ident = identity.extract(live, ga) if live else None
    email = identity.email_of(ident) or (ga or {}).get("active") or ""
    if not email:
        raise AgysError("当前未登录（没有可用的活跃凭据）")
    rep.set(email=email, identity=ident)
    rep.msg(email)


def cmd_logout(args, rep, store, v):
    with SwitchLock():
        store.delete()
        write_ga({"active": "", "old": []})
        v["current"] = None
        save_vault(v)
        audit.log("logout", result="ok")
        rep.msg(f"{APP}: 已登出（活跃凭据已清除，所有帐号仍保留）。"
                f"用 agys use <帐号> 或 agys auto 重新开始")
        rep.set(logged_out=True)


# ---------------------------------------------------------------- 补全 / 帮助

def cmd_completion(args, rep, store, v):
    script = COMPLETION[args.shell]
    rep.set(shell=args.shell, script=script)
    rep.msg(script)


def cmd_help(args, rep, store, v):
    topic = args.topic
    if not topic:
        rep.msg(f"{APP} 帮助主题：" + ", ".join(TOPICS))
        rep.msg("用法：agys help <主题>；完整命令参考见 docs/COMMANDS.md")
        rep.set(topics=list(TOPICS))
        return
    if topic not in TOPICS:
        raise AgysError(f"未知主题 '{topic}'，可选：{', '.join(TOPICS)}")
    rep.set(topic=topic, text=TOPICS[topic])
    rep.msg(TOPICS[topic])

