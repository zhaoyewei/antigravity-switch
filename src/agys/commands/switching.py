"""切换类命令：use / tui / as / auto。

`auto` 是裸 `agys` 的默认行为：不指定帐号，按额度与可用性挑一个，
必要时切换并启动 agy；agy 非零退出时探测确认真实状态——是额度用尽
（429）就提醒并自动换下一个帐号重试，无论发生在启动瞬间还是会话中途
（绝不主动打断正在跑的会话，只在它已经退出之后处理）。
"""
from __future__ import annotations

import os
import sys
import time

from .. import APP, quota, tui
from ..common import AgysError, SwitchLock, pad
from ..runtime import (
    launch, pick_account, resolve_or_pick, switch_if_needed, switch_to,
)

# 短于该窗口的失败视为「启动即失败」（只影响提示措辞）；
# 换号与否一律由探测确认，不再由窗口决定
DEFAULT_FASTFAIL = 20.0
# 用户主动取消不该被当成失败
CANCEL_CODES = {130, 2}


def _fallback_window():
    try:
        return float(os.environ.get("AGYS_AUTO_FASTFAIL") or DEFAULT_FASTFAIL)
    except ValueError:
        return DEFAULT_FASTFAIL


def _env_flag(name):
    return (os.environ.get(name) or "").strip().lower() in ("1", "true", "yes", "on")


# ---------------------------------------------------------------- use / tui

def cmd_use(args, rep, store, v):
    acc_id = resolve_or_pick(args, rep, store, v, args.name)
    with SwitchLock():
        switch_to(acc_id, args, rep, store, v)


def cmd_tui(args, rep, store, v):
    name = pick_account(args, rep, store, v, title="agys 帐号切换（Enter 确认）")
    acc_id = resolve_or_pick(args, rep, store, v, name)
    with SwitchLock():
        switch_to(acc_id, args, rep, store, v)


# ---------------------------------------------------------------- as

def _post_launch_check(acc_id, rep):
    """agy 退出非零后顺手确认是不是额度问题；是就提醒一句（`as` 用，不自动换号）。"""
    report = _probe_after_failure(acc_id, rep)
    if report and report.get("state") == "exhausted":
        quota.mark(acc_id, "exhausted", "as 退出后探测确认")
        rep.warn(f"帐号 '{acc_id}' 的额度已用尽；运行 agys 可自动换到其它帐号继续")


def cmd_as(args, rep, store, v):
    tail = args.args_cmd or []
    if tail and tail[0] == "--":
        tail = tail[1:]
    if not args.name:
        raise AgysError("用法：agys as <帐号> [--] [agy 的参数...]")
    acc_id = resolve_or_pick(args, rep, store, v, args.name)
    switch_if_needed(acc_id, args, rep, store, v)
    rc = launch(tail, rep)
    if rc != 0 and rc not in CANCEL_CODES:
        _post_launch_check(acc_id, rep)
    sys.exit(rc)


# ---------------------------------------------------------------- auto

def _render_status(rep, reports, v):
    """把各帐号的探测结果排成表（按显示宽度对齐，中文列不会歪）。"""
    current = v.get("current")
    rep.msg(f"{APP}: 帐号额度与可用性（按优先级排序）")
    rep.msg(f"  {'':2} {pad('ID', 18)} {pad('状态', 16)} {pad('邮箱', 26)} 说明")
    for r in reports:
        mark = "*" if r["id"] == current else " "
        rep.msg(f"  {mark:2} {pad(r['id'], 18)} {pad(quota.label(r), 16)} "
                f"{pad(r.get('email') or '-', 26)} {r.get('detail') or ''}")
    if any(r.get("state") == "unknown" for r in reports):
        rep.msg("  「额度未知」= 该帐号没有可查询的配额包（免费帐号），"
                "已通过健康探针确认凭据可用")
    rep.msg("  提示：额度数据来自 Antigravity 的配额接口，免费帐号不提供百分比；"
            "缓存 5 分钟，加 --offline 只看缓存")


def _probe_after_failure(acc_id, rep):
    """agy 快速失败后确认到底是不是额度问题。"""
    try:
        report = quota.probe(acc_id)
    except Exception as e:
        rep.warn(f"探测 '{acc_id}' 失败：{e}")
        return None
    return report


def _run_with_fallback(order, args, rep, store, v, tail):
    """按顺序启动 agy；agy 非零退出且「确认」额度用尽就换下一个。

    不再区分「启动即失败」与「会话中途退出」：只要 agy 已经退出
    （绝不打断正在跑的会话），就探测确认真实状态——429 / 额度耗尽
    才换号，其它错误原样返回，让用户看到真实输出。
    调用前 `cmd_auto` 已经切到 `order[0]`，所以首个帐号不再重复切换
    （否则会多打一行「已是当前帐号」）。
    """
    window = _fallback_window()
    rc = 0
    for idx, acc_id in enumerate(order):
        if idx:
            rep.msg(f"{APP}: 尝试下一个帐号 '{acc_id}'")
            switch_if_needed(acc_id, args, rep, store, v)
        started = time.monotonic()
        rc = launch(tail, rep)
        elapsed = time.monotonic() - started
        if rc == 0 or rc in CANCEL_CODES:
            return rc
        report = _probe_after_failure(acc_id, rep)
        if report is None or report.get("state") != "exhausted":
            # 不是额度问题就别乱换号，原样返回让用户看到真实错误
            if elapsed >= window:
                rep.warn(f"agy 会话运行 {elapsed:.0f} 秒后退出（rc={rc}），"
                         "探测确认不是额度问题，请查看上方 agy 的输出")
            return rc
        quota.mark(acc_id, "exhausted", f"agy {elapsed:.0f}s 后退出（rc={rc}）")
        if idx + 1 >= len(order):
            rep.warn(f"帐号 '{acc_id}' 的额度已用尽（agy 运行 {elapsed:.0f} 秒后退出），"
                     "且没有更多帐号可换。额度重置或重新登录后再运行 agys；"
                     "刚才会话仍可用 agys history 查看")
            return rc
        rep.warn(f"帐号 '{acc_id}' 的额度已用尽（agy 运行 {elapsed:.0f} 秒后退出），"
                 f"自动切换到下一个帐号继续")
    return rc


def cmd_auto(args, rep, store, v):
    """按额度挑帐号。裸 `agys` 即此命令。"""
    if not v["accounts"]:
        raise AgysError("还没有任何帐号。用 agys add 添加第一个（会自动保存当前登录）。")

    tail = getattr(args, "args_cmd", None) or []
    if tail and tail[0] == "--":
        tail = tail[1:]

    offline = bool(getattr(args, "auto_offline", False)) or _env_flag("AGYS_AUTO_OFFLINE")
    tag = getattr(args, "auto_tag", None)
    ids = None
    if tag:
        ids = [acc for acc, m in v["accounts"].items() if tag in (m.get("tags") or [])]
        if not ids:
            raise AgysError(f"没有帐号打了标签 '{tag}'。"
                            "用 agys tag <帐号> <标签> 打标签，agys tag 看现有标签")
    reports = quota.snapshot(v, offline=offline, ids=ids)
    rep.set(accounts=reports, tag=tag or None)

    if getattr(args, "auto_status", False):
        _render_status(rep, reports, v)
        return
    if getattr(args, "auto_dry_run", False):
        _render_status(rep, reports, v)
        best = reports[0]
        rep.msg(f"{APP}: 会选中 '{best['id']}'（{quota.describe(best)}）")
        rep.set(choice=best["id"])
        return

    usable = [r["id"] for r in reports if quota.usable(r)]
    if not usable:
        # 探测失败（多半是网络 / 代理问题）不等于帐号不能用，退一步按顺序试，
        # 免得因为一个坏代理把用户彻底挡在门外。
        usable = [r["id"] for r in reports if r.get("state") == "error"]
        if usable:
            rep.warn("所有帐号的额度探测都没有成功（可能是网络或代理问题），"
                     "先按顺序尝试：" + "、".join(usable))
        else:
            worst = reports[0]
            raise AgysError(
                f"没有可用帐号：'{worst['id']}' {quota.describe(worst)}。\n"
                "先运行 agys auto --status 看全部帐号，或用 agys add 重新登录一个。")
    for r in reports:
        if r["id"] in usable:
            continue
        rep.warn(f"跳过帐号 '{r['id']}'：{quota.describe(r)}")

    chosen = usable[0]
    switch_if_needed(chosen, args, rep, store, v)
    rep.set(choice=chosen)

    if not getattr(args, "auto_launch", True):
        rep.msg(f"{APP}: 已切到 '{chosen}'（--no-launch，未启动 agy）")
        return
    if not tui.interactive():
        rep.msg(f"{APP}: 非交互终端，只完成切换、不启动 agy（需要时手动运行 agy）")
        return
    sys.exit(_run_with_fallback(usable, args, rep, store, v, tail))
