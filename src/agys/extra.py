"""扩展命令：引导、状态、脚本友好输出、备份恢复、补全与帮助。"""
from __future__ import annotations

import datetime
import os
import shutil
import tarfile
import tempfile
import time

from . import agy_install, audit, doctor, identity, journal
from .common import AgysError, SwitchLock, confirm, read_ga, write_ga
from .config import paths
from .crypto import secure_dir
from .vault import (
    email_slug, find_by_identity, load_profile, migrate_profiles,
    resolve, save_profile, save_vault, slugify,
)

COMMANDS = ("add list current use as switch run ls alias rename remove rm export "
            "import log layout doctor version update init status whoami logout "
            "info default completion backup restore check help ids").split()

TOPICS = {
    "commands": """常用命令
  agys init              首次引导：检查/安装 agy，收录当前登录
  agys add [名字]        添加一个帐号（自动保存当前登录，再走浏览器登录）
  agys list              列出帐号（* = 当前）
  agys use <帐号>        切换帐号
  agys as <帐号> [参数]  切换并以该帐号启动 agy，参数透传
  agys status            一行状态概览
  agys whoami            输出当前活跃邮箱（适合脚本）
  agys info <帐号>       查看帐号详情与 token 有效期
  agys logout            登出但保留所有帐号
  agys doctor            环境自检；--fix 自动修复
  agys completion bash   生成 shell 补全脚本
  agys backup / restore  完整备份与恢复

完整参考：docs/COMMANDS.md""",
    "workflows": """典型流程
  第一次        curl -fsSL .../install.sh | bash && agys init
  加第二个号    agys add work      （浏览器登录后自动生效）
  日常切换      agys use work  /  agys as work -p "review this diff"
  查看当前      agys status  /  agys whoami
  换机器        agys export → 新机 agys import xxx.json → agys use <id>
  整机备份      agys backup → ~/.agy-accounts/backups/…tar.gz
  升级          agys update  /  agys check""",
    "troubleshooting": """排障
  切换不生效    先 agys doctor；若布局指纹变化，agys layout 对比后用
                --allow-layout-change 接受（仅在你确认 agy 升级过之后）
  切换被拒绝    有 agy 进程在跑；用 --close-all 自动关闭后切换，或手动退出
  凭据未纳管    agys current 会标红；下次 use/add 会自动收录
  找不到 agy    agys init 会自动用官方脚本安装；也可设置 AGYS_AGY_BIN
  IDE 显示旧号  CLI 与 IDE 共享凭据，IDE 窗口执行 Developer: Reload Window
  token 被轮换  切换前会把刷新后的 token 回收进对应 profile，无需手动处理

更多：docs/TROUBLESHOOTING.md""",
    "env": """环境变量
  AGYS_HOME            vault 目录（默认 ~/.agy-accounts）
  AGYS_GEMINI_HOME     agy 配置目录（默认 ~/.gemini）
  AGYS_AGY_BIN         agy 二进制路径（也可写 "python stub.py" 做测试）
  AGYS_AGY_INSTALL_CMD 自定义 agy 安装命令
  AGYS_NO_AUTO_INSTALL=1  关闭 agy 自动安装
  AGYS_NO_ENCRYPT=1      本地 vault 明文（不推荐，仅迁移用）
  AGYS_BACKEND=memory    测试后端，不碰真实凭据
  AGYS_PROCESS_NAMES     自定义进程名列表
  --json                结构化输出，便于脚本集成""",
    "security": """安全模型
  本地 vault 加密：Windows DPAPI / macOS·Linux SHAKE256+HMAC，密钥 0600
  导出文件是明文（迁移用途），默认落在 ~/.agy-accounts/exports/
  备份 tar.gz 含加密后的凭据与密钥，请按敏感文件保管
  切换有事务日志，崩溃后下次启动自动回滚
  报告漏洞请看 SECURITY.md，不要公开 issue""",
}


# ---------------------------------------------------------------- 引导与状态

def cmd_init(args, rep, store, v):
    info = agy_install.describe()
    rep.set(agy=info)
    rep.msg(f"agys: agy = {info['location'] or '未安装'}")
    if not info["installed"]:
        rep.warn("agy 未安装（自动安装可能被 AGYS_NO_AUTO_INSTALL=1 关闭）。"
                 "可设置 AGYS_AGY_BIN 指向已有二进制，或查看 agys help troubleshooting")
    live = store.get()
    ga = read_ga()
    if live is None:
        rep.msg("agys: 当前尚未登录 agy。下一步：agys add（会打开浏览器登录）")
        rep.set(accounts=len(v["accounts"]), logged_in=False)
        return
    ident = identity.extract(live, ga)
    matched = find_by_identity(ident, v)
    if matched:
        rep.msg(f"agys: 当前登录已是纳管帐号 '{matched}'")
    else:
        em = identity.email_of(ident)
        acc = email_slug(em) or slugify(identity.short(ident))
        save_profile(acc, live, ga, {"email": em, "identity": ident})
        v["accounts"][acc] = {"id": acc, "email": em, "aliases": [], "identity": ident}
        v["current"] = acc
        save_vault(v)
        rep.msg(f"agys: 已把当前登录收录为帐号 '{acc}'（{em or ident}）")
    rep.msg("agys: 下一步：agys add 添加另一个帐号；agys use / agys as 随时切换")
    rep.set(accounts=len(v["accounts"]), logged_in=True, identity=ident)


def cmd_status(args, rep, store, v):
    d = doctor.collect(store)
    procs = d["running_processes"]
    nproc = "未知" if procs is None else str(len(procs))
    consistent = "一致" if d["vault"]["current"] == d["credential_matches"] else "不一致"
    line = (f"当前 {d['vault']['current'] or '无'} | 活跃 {d['credential_identity'] or '无'} "
            f"({consistent}) | 帐号 {d['vault']['accounts']} | 进程 {nproc} | "
            f"加密 {d['encryption']} | agy {d['agy_version']}")
    rep.msg(line)
    rep.set(current=d["vault"]["current"], active_identity=d["credential_identity"],
            consistent=consistent == "一致", accounts=d["vault"]["accounts"],
            running_processes=nproc, encryption=d["encryption"],
            agy_version=d["agy_version"], warnings=d["warnings"])


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
        rep.msg("agys: 已登出（活跃凭据已清除，所有帐号仍保留）。"
                "用 agys use <帐号> 或 agys as <帐号> 重新登录")
        rep.set(logged_out=True)


def cmd_ids(args, rep, store, v):
    ids = []
    for acc, meta in sorted(v["accounts"].items()):
        ids.append(acc)
        ids.extend(meta.get("aliases") or [])
    rep.set(ids=ids)
    for x in ids:
        rep.msg(x)


# ---------------------------------------------------------------- 帐号详情 / 默认

def _token_expiry(blob):
    """尽力从 token 中解析过期时间，返回 ISO 字符串或 None。"""
    import json as _json
    try:
        data = _json.loads(blob.decode("utf-8"))
    except Exception:
        return None
    def walk(o, depth=0):
        if depth > 6:
            return None
        if isinstance(o, dict):
            for k, val in o.items():
                lk = str(k).lower()
                if lk in ("expiry", "expires_at", "expiry_date", "exp") and val:
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
    meta = v["accounts"].get(acc, {})
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
            rep.msg(f"agys: 默认帐号已设为 '{acc}'")
        rep.set(default=v.get("default"))
        if not args.name:
            rep.msg(f"默认帐号：{v.get('default') or '未设置'}")


# ---------------------------------------------------------------- 自检修复

def doctor_fix(rep, store, v):
    notes = []
    n = migrate_profiles()
    if n:
        notes.append(f"迁移 {n} 个明文 profile 为加密格式")
    msg = journal.recover(store)
    if msg:
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
    if not notes:
        rep.msg("  没有发现需要修复的问题")


# ---------------------------------------------------------------- 补全

COMPLETION = {
    "bash": """# bash: 加到 ~/.bashrc
_agys_complete() {
  local cur cmds ids
  cur="${COMP_WORDS[COMP_CWORD]}"
  cmds="%s"
  ids="$(agys ids 2>/dev/null)"
  COMPREPLY=( $(compgen -W "$cmds $ids" -- "$cur") )
}
complete -F _agys_complete agys
""" % " ".join(COMMANDS),
    "zsh": """#compdef agys
# zsh: 存为 _agys 并放到 fpath 中
_agys() {
  local -a cmds ids
  cmds=(%s)
  ids=(${(f)"$(agys ids 2>/dev/null)"})
  _describe 'agys' cmds
  _describe 'accounts' ids
}
compdef _agys agys
""" % " ".join(COMMANDS),
    "fish": """# fish: 存为 ~/.config/fish/completions/agys.fish
complete -c agys -f
complete -c agys -n '__fish_use_subcommand' -a '%s'
complete -c agys -n '__fish_seen_subcommand_from use as switch run info alias rename remove rm default' -a '(agys ids 2>/dev/null)'
""" % " ".join(COMMANDS),
    "powershell": """# PowerShell: 加到 $PROFILE
Register-ArgumentCompleter -Native -CommandName 'agys' -ScriptBlock {
  param($wordToComplete, $commandAst, $cursorPosition)
  $cmds = @(%s)
  $ids = (agys ids 2>$null) -split "`n"
  ($cmds + $ids) | Where-Object { $_ -like "$wordToComplete*" } |
    ForEach-Object { [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterValue', $_) }
}
""" % ", ".join("'%s'" % c for c in COMMANDS),
}


def cmd_completion(args, rep, store, v):
    script = COMPLETION[args.shell]
    rep.set(shell=args.shell, script=script)
    rep.msg(script)


# ---------------------------------------------------------------- 备份 / 恢复

def cmd_backup(args, rep, store, v):
    home = paths().home
    path = args.path or os.path.join(
        home, "backups", f"agys-backup-{datetime.date.today().isoformat()}-{int(time.time())}.tar.gz")
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    skip_dirs = {"backups", "__pycache__"}
    skip_files = {".switch.lock", "pending.json", "memory_credential.json"}
    with tarfile.open(path, "w:gz") as tar:
        for root, dirs, files in os.walk(home):
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            for f in files:
                if f in skip_files or f == os.path.basename(path):
                    continue
                full = os.path.join(root, f)
                tar.add(full, arcname=os.path.relpath(full, home))
    rep.msg(f"agys: 已备份到 {path}")
    rep.msg("agys: 注意：备份内含加密后的登录凭据与密钥，请按敏感文件保管。")
    rep.set(path=path, size=os.path.getsize(path))


def cmd_restore(args, rep, store, v):
    if not os.path.isfile(args.path):
        raise AgysError(f"备份文件不存在：{args.path}")
    if not confirm(f"恢复备份将覆盖当前 vault 与帐号数据（{args.path}）", args.yes):
        raise AgysError("已取消")
    tmp = tempfile.mkdtemp(prefix="agys-restore-")
    try:
        with tarfile.open(args.path, "r:gz") as tar:
            members = [m for m in tar.getmembers()
                       if not os.path.isabs(m.name) and ".." not in m.name.split("/")
                       and m.isfile()]
            try:
                tar.extractall(tmp, members=members, filter="data")
            except TypeError:
                # Python < 3.12 没有 filter 参数；members 已做路径校验
                tar.extractall(tmp, members=members)
        if not os.path.isfile(os.path.join(tmp, "vault.json")):
            raise AgysError("备份中缺少 vault.json，拒绝恢复")
        home = paths().home
        secure_dir(home)
        with SwitchLock():
            for name in ("vault.json", "audit.jsonl", ".vault.key"):
                src = os.path.join(tmp, name)
                if os.path.isfile(src):
                    shutil.copy2(src, os.path.join(home, name))
            src_prof = os.path.join(tmp, "profiles")
            if os.path.isdir(src_prof):
                os.makedirs(os.path.join(home, "profiles"), exist_ok=True)
                for acc in os.listdir(src_prof):
                    s = os.path.join(src_prof, acc)
                    if os.path.isdir(s):
                        shutil.copytree(s, os.path.join(home, "profiles", acc),
                                        dirs_exist_ok=True)
        audit.log("restore", result="ok", detail=os.path.basename(args.path))
        rep.msg(f"agys: 已从 {args.path} 恢复。请运行 agys use <id> 让活跃凭据与恢复后的 vault 对齐。")
        rep.set(restored=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- 检查 / 帮助

def cmd_check(args, rep, store, v):
    import urllib.request
    from . import __version__
    owner = os.environ.get("AGYS_GITHUB_OWNER", "zhaoyewei")
    url = (f"https://raw.githubusercontent.com/{owner}/antigravity-switch/main/"
           "src/agys/__init__.py")
    latest = None
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            text = r.read().decode("utf-8")
        latest = text.split('__version__ = "')[1].split('"')[0]
    except Exception as e:
        rep.warn(f"无法查询最新版本（离线或网络受限）：{e}")
    d = doctor.collect(store)
    rep.set(current=__version__, latest=latest,
            issues=len(d["warnings"]), warnings=d["warnings"])
    rep.msg(f"agys {__version__}" + (f" → 仓库最新 {latest}" if latest else "（版本检查跳过）"))
    rep.msg(f"自检：{len(d['warnings'])} 条提示；详细报告用 agys doctor")


def cmd_help(args, rep, store, v):
    topic = args.topic
    if not topic:
        rep.msg("agys 帮助主题：" + ", ".join(TOPICS))
        rep.msg("用法：agys help <主题>；完整命令参考见 docs/COMMANDS.md")
        rep.set(topics=list(TOPICS))
        return
    if topic not in TOPICS:
        raise AgysError(f"未知主题 '{topic}'，可选：{', '.join(TOPICS)}")
    text = TOPICS[topic]
    rep.set(topic=topic, text=text)
    rep.msg(text)
