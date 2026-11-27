"""命令行入口：只负责解析参数、分派命令、统一错误处理。

具体实现按域放在 `commands/` 下；跨命令的流程在 `runtime.py`。
这一层刻意保持「薄」——想加命令就只改这里和 commands/ 下对应文件。
"""
from __future__ import annotations

import argparse
import json
import sys

from . import APP, __version__, layout
from .commands import (
    cmd_add, cmd_alias, cmd_as, cmd_auto, cmd_backup, cmd_check, cmd_completion,
    cmd_current, cmd_default, cmd_doctor, cmd_export, cmd_help, cmd_history, cmd_ids,
    cmd_import, cmd_info, cmd_init, cmd_layout, cmd_list, cmd_log, cmd_logout,
    cmd_prompt, cmd_proxy, cmd_remove, cmd_rename, cmd_restore, cmd_stats,
    cmd_status, cmd_tag, cmd_tui, cmd_update, cmd_use, cmd_version, cmd_watch,
    cmd_whoami,
)
from .common import AgysError, Reporter
from .credentials import CredentialError, get_store
from .crypto import CryptoError
from .helptext import COMPLETION, TOPICS
from .runtime import ensure_ready
from .vault import load_vault

ALIASES = {"ls": "list", "switch": "use", "run": "as", "rm": "remove"}
# 这些命令会写凭据，布局异常时必须拒绝执行
STRICT = frozenset({"add", "use", "as", "tui", "auto", "import"})

# `as` / `auto` 里，argparse REMAINDER 会吞掉 agys 自己的 flag，
# 所以先把它们提到帐号名之前。
REORDER_CMDS = ("as", "run", "auto")
GUARD_FLAGS = {"--no-guard", "--close-all", "--yes", "--allow-layout-change"}
AUTO_FLAGS = {"--status", "--dry-run", "--offline", "--no-launch", "--tag"}


def _guard_flags(sp, with_yes=True):
    g = sp.add_mutually_exclusive_group()
    g.add_argument("--no-guard", action="store_true",
                   help="不检测/不关闭运行中的 agy 进程（风险自负）")
    g.add_argument("--close-all", action="store_true",
                   help="自动关闭运行中的 agy 进程后再切换，切换完尽力重开")
    if with_yes:      # import 已有语义相近的 --yes，避免重复定义
        sp.add_argument("--yes", action="store_true",
                        help="跳过交互确认（配合 --close-all / remove）")
    sp.add_argument("--allow-layout-change", action="store_true",
                    help="跳过自动发现，直接把当前布局记为基准")


def _subcommands(parser):
    """从 parser 里取出已注册的子命令名（含别名），避免另存一份容易失效的清单。"""
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return set(action.choices)
    return set()


def _default_to_auto(argv, parser):
    """裸 `agys` 等同于 `agys auto`。

    只有「没写子命令」时才补 `auto`：如果出现了一个不认识的普通词（比如把
    `list` 打成 `lst`），保持原样交给 argparse 报错，而不是悄悄把它当成
    agy 的参数启动一个进程。
    """
    known = _subcommands(parser)
    for token in argv:
        if token == "--":
            break
        if token in known:
            return argv
        if not token.startswith("-"):
            return argv          # 有非 flag 首词却不是命令 → 让 argparse 报错
    pos = 0
    while pos < len(argv) and argv[pos] == "--json":
        pos += 1                 # 全局 flag 留在子命令之前
    return argv[:pos] + ["auto"] + argv[pos:]


def _reorder_as_flags(argv):
    """把子命令后面出现的 agys 自身 flags 提到前面；`--` 之后一律透传给 agy。"""
    a = list(argv)
    idx = next((i for i, x in enumerate(a) if x in REORDER_CMDS), None)
    if idx is None:
        return a
    head, rest = a[:idx + 1], a[idx + 1:]
    known = set(GUARD_FLAGS)
    if a[idx] in ("as", "run"):
        known.add("--json")
    else:
        known |= AUTO_FLAGS
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
        epilog="直接运行 agys = 按额度自动挑帐号并启动 agy（同 agys auto）。"
               "`--` 之后的参数全部透传给 agy。")
    p.add_argument("--json", action="store_true", help="以 JSON 输出（便于脚本集成）")
    p.add_argument("--version", action="version", version=f"{APP} {__version__}")
    sub = p.add_subparsers(dest="cmd")

    # ---- 切换 ----
    sp = sub.add_parser("auto", help="按额度自动挑帐号并启动 agy（裸 agys 即此命令）")
    sp.add_argument("--status", dest="auto_status", action="store_true",
                    help="只显示各帐号的额度与可用性")
    sp.add_argument("--dry-run", dest="auto_dry_run", action="store_true",
                    help="只报告会选中谁，不切换也不启动")
    sp.add_argument("--offline", dest="auto_offline", action="store_true",
                    help="只用额度缓存，不联网探测")
    sp.add_argument("--no-launch", dest="auto_launch", action="store_false",
                    help="只切换，不启动 agy")
    sp.add_argument("--tag", dest="auto_tag",
                    help="只在打了该标签的帐号里选（agys tag 设置标签）")
    sp.add_argument("args_cmd", nargs=argparse.REMAINDER,
                    help="透传给 agy 的参数（建议用 -- 分隔）")
    _guard_flags(sp)
    sp.set_defaults(func=cmd_auto)

    sp = sub.add_parser("use", aliases=["switch"],
                        help="切换帐号（id / 邮箱 / 别名 / 唯一前缀）")
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

    # ---- 帐号 ----
    sp = sub.add_parser("add", help="添加帐号（先保存当前登录，再走 agy 登录流程）")
    sp.add_argument("name", nargs="?", help="帐号 id（缺省用登录邮箱局部名）")
    sp.add_argument("--alias", action="append", help="添加别名（可重复）")
    _guard_flags(sp)
    sp.set_defaults(func=cmd_add)

    sp = sub.add_parser("list", aliases=["ls"], help="列出所有帐号")
    sp.set_defaults(func=cmd_list)

    sub.add_parser("current", help="查看当前帐号与活跃凭据是否一致").set_defaults(
        func=cmd_current)

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

    sp = sub.add_parser("info", help="查看帐号详情与 token 过期时间")
    sp.add_argument("name", nargs="?", help="帐号（缺省用当前帐号）")
    sp.set_defaults(func=cmd_info)

    sp = sub.add_parser("default", help="查看 / 设置默认帐号")
    sp.add_argument("name", nargs="?", help="要设为默认的帐号；省略则查看")
    sp.set_defaults(func=cmd_default)

    sp = sub.add_parser("tag", help="给帐号打标签（auto --tag 在子集内选号）；"
                                    "不带参数时列出全部标签")
    sp.add_argument("name", nargs="?", help="帐号")
    sp.add_argument("tags", nargs="*", help="标签（可多个）")
    sp.add_argument("--remove", action="store_true", help="移除这些标签")
    sp.set_defaults(func=cmd_tag)

    sub.add_parser("ids", help="列出所有 id 与别名（供补全 / 脚本使用）").set_defaults(
        func=cmd_ids)

    # ---- 迁移 ----
    sp = sub.add_parser("export", help="导出所有帐号（明文，迁移用途）")
    sp.add_argument("path", nargs="?", help="输出路径（缺省 ~/.agy-accounts/exports/）")
    sp.set_defaults(func=cmd_export)

    sp = sub.add_parser("import", help="导入导出文件，或从 agy 用户文件夹导入已有登录态"
                                       "（后者不需要重新登录）")
    sp.add_argument("path", help="agys 导出文件（*.json），或 agy 用户文件夹（免登录导入）")
    sp.add_argument("--name", help="导入后的帐号 id（仅文件夹导入；缺省用邮箱局部名）")
    sp.add_argument("--dry-run", action="store_true",
                    help="只显示扫描到哪个凭据、会导入成什么，不写入任何东西")
    sp.add_argument("--use", action="store_true", help="导入后立即切换到这个帐号")
    sp.add_argument("--no-verify", action="store_true", help="跳过校验和检查")
    sp.add_argument("--on-conflict", default="overwrite",
                    choices=("ask", "skip", "overwrite", "rename"),
                    help="id 已存在时的处理方式：ask 逐个询问 / skip 保留现有 / "
                         "overwrite 覆盖（默认）/ rename 换个 id 并存")
    sp.add_argument("--yes", action="store_true",
                    help="配合 --on-conflict ask：冲突时一律覆盖")
    _guard_flags(sp, with_yes=False)
    sp.set_defaults(func=cmd_import)

    sp = sub.add_parser("backup", help="备份整个 vault 为 tar.gz")
    sp.add_argument("path", nargs="?", help="输出路径（缺省 ~/.agy-accounts/backups/）")
    sp.set_defaults(func=cmd_backup)

    sp = sub.add_parser("restore", help="从 tar.gz 备份恢复（覆盖当前数据）")
    sp.add_argument("path")
    sp.add_argument("--yes", action="store_true", help="跳过确认")
    sp.set_defaults(func=cmd_restore)

    # ---- 诊断 ----
    sp = sub.add_parser("doctor", help="环境自检；--fix 自动修复常见问题")
    sp.add_argument("--fix", action="store_true",
                    help="迁移明文 profile / 回滚未完成事务 / 修复索引 / 收紧权限")
    sp.set_defaults(func=cmd_doctor)

    sp = sub.add_parser("layout", help="显示 agy 存储布局；--discover 列候选，--adopt 自动适配")
    sp.add_argument("--discover", action="store_true", help="列出候选布局（只读探测）")
    sp.add_argument("--adopt", action="store_true",
                    help="自动发现并采纳可用布局；无候选时把当前布局记为基准")
    sp.set_defaults(func=cmd_layout)

    sp = sub.add_parser("log", help="查看切换审计日志")
    sp.add_argument("-n", "--limit", type=int, default=20)
    sp.set_defaults(func=cmd_log)

    sp = sub.add_parser("stats", help="帐号使用统计：切换次数 / 最后切换时间（只读）")
    sp.set_defaults(func=cmd_stats)

    sp = sub.add_parser("watch", help="持续监控帐号额度并在异常时提醒（Ctrl+C 停止）")
    sp.add_argument("--interval", type=int, default=300,
                    help="探测间隔秒数（最小 30，默认 300）")
    sp.add_argument("--low", type=float, default=0.1,
                    help="当前帐号剩余额度低于该比例时提醒（默认 0.1）")
    sp.add_argument("--once", action="store_true",
                    help="只探测一轮就退出（适合 cron / 计划任务）")
    sp.set_defaults(func=cmd_watch)

    sub.add_parser("version", help="显示版本").set_defaults(func=cmd_version)

    sp = sub.add_parser("update", help="重新运行安装脚本升级 agys")
    sp.add_argument("--check", action="store_true", help="只检查最新版本")
    sp.set_defaults(func=cmd_update)

    sub.add_parser("check", help="检查新版本并做快速自检").set_defaults(func=cmd_check)

    # ---- 日常 ----
    sub.add_parser("init", help="首次引导：检测/安装 agy 并收录当前登录").set_defaults(
        func=cmd_init)
    sub.add_parser("status", help="一行状态概览（当前 / 活跃 / 进程 / 加密）").set_defaults(
        func=cmd_status)
    sub.add_parser("whoami", help="输出当前活跃邮箱（脚本友好）").set_defaults(
        func=cmd_whoami)

    sp = sub.add_parser("prompt", help="输出当前帐号（shell 提示符集成用）")
    sp.add_argument("fmt", nargs="?", default="{id}",
                    help="格式串，可用 {id} 与 {email}，如 'agy:{id}'")
    sp.set_defaults(func=cmd_prompt)

    sub.add_parser("logout", help="登出并清除活跃凭据，但保留所有帐号").set_defaults(
        func=cmd_logout)

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

    sp = sub.add_parser("proxy", help="配置 agy 子进程使用的代理（不改系统代理）")
    psub = sp.add_subparsers(dest="proxy_cmd")
    psub.add_parser("show", help="查看当前代理配置与来源").set_defaults(func=cmd_proxy)
    pset = psub.add_parser("set", help="设置代理，例如 http://127.0.0.1:7890")
    pset.add_argument("url", help="代理地址（http / https / socks5）")
    pset.add_argument("--no-proxy",
                      help="NO_PROXY 列表（逗号分隔），默认追加 localhost/127.0.0.1/::1")
    pset.set_defaults(func=cmd_proxy)
    psub.add_parser("clear", help="清除代理配置").set_defaults(func=cmd_proxy)
    ptest = psub.add_parser("test", help="测试代理连通性")
    ptest.add_argument("url", nargs="?", help="要测试的代理；缺省用当前配置")
    ptest.set_defaults(func=cmd_proxy)
    sp.set_defaults(func=cmd_proxy)

    sp = sub.add_parser("completion", help="生成 shell 补全脚本")
    sp.add_argument("shell", choices=sorted(COMPLETION))
    sp.set_defaults(func=cmd_completion)

    sp = sub.add_parser("help", help="查看内置帮助主题")
    sp.add_argument("topic", nargs="?", choices=sorted(TOPICS),
                    help=" / ".join(sorted(TOPICS)))
    sp.set_defaults(func=cmd_help)

    # 裸 `agys` = auto
    p.set_defaults(func=cmd_auto, auto_status=False, auto_dry_run=False,
                   auto_offline=False, auto_launch=True, args_cmd=[])
    return p


def _is_readonly(args):
    """只读命令不该被布局异常挡住：得先能看到状态，才谈得上修。"""
    if args.cmd == "auto":
        return bool(getattr(args, "auto_status", False)
                    or getattr(args, "auto_dry_run", False))
    if args.cmd == "import":
        # 只有 --use 会写凭据；单纯导入只动 vault
        return not (getattr(args, "use", False)
                    and not getattr(args, "dry_run", False))
    return False


def _ensure_utf8():
    """Windows 上统一 stdout/stderr 为 UTF-8。

    PyInstaller 打出的单文件程序在中文 Windows 上默认按 cp936 写管道输出，
    而源码运行（UTF-8 模式）写的是 UTF-8 —— 同一个二进制被 `agys ... | jq`
    或 Git Bash 接住时中文会乱码。Windows 控制台本身用 UTF-8 宽字符写入，
    所以把 TextIOWrapper 统一成 UTF-8 对交互显示也无害。
    """
    if sys.platform != "win32":
        return
    for stream in (sys.stdout, sys.stderr):
        try:
            enc = (getattr(stream, "encoding", "") or "").lower().replace("-", "")
            if enc not in ("utf8", "utf_8") and hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError, AttributeError):
            pass


def main(argv=None):
    _ensure_utf8()
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    argv = _default_to_auto(argv, parser)
    argv = _reorder_as_flags(argv)
    args = parser.parse_args(argv)
    # 别名规范化：保证 strict 校验与 NEEDS_AGY 判断都基于主命令名
    args.cmd = ALIASES.get(args.cmd, args.cmd) or "auto"
    rep = Reporter(args.json)
    try:
        v = load_vault()
        # 上次自动适配的布局必须先落到进程配置，之后才能构造凭据后端
        layout.apply_cached(v)
        store = get_store()
        strict = args.cmd in STRICT and not _is_readonly(args)
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
