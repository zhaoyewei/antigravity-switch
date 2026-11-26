"""`agys history` —— 只读查看 agy 会话历史。

历史目录本身不按帐号分区，所有帐号共用同一份，所以这里不区分帐号。
"""
from __future__ import annotations

import json
import os
import time

from .. import history
from ..common import AgysError
from ..config import paths
from ..crypto import secure_dir


def cmd_history(args, rep, store, v):
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
        rep.msg(f"会话：{row['title'] or '(未命名会话)'}")
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
        rep.msg(f"已导出 {payload['count']} 个会话到 {target}")
        return

    search = args.search or (args.target if action == "search" else None)
    items = history.collect(search=search, workspace=args.workspace,
                            limit=limit, include_orphans=orphans)
    rep.set(count=len(items), conversations=items)
    if not items:
        rep.msg("没有匹配的会话。")
        return
    rep.msg(f"{len(items)} 个会话（agy 历史不按帐号分区，所有帐号共用同一份）")
    for i in items:
        flag = "?" if i["source"] == "scan" else " "
        rep.msg(f" {flag} {i['updated'] or '-':<19} {i['steps']:>4}步  "
                f"{i['id'][:8]}  {(i['title'] or '(未命名会话)')[:46]}")
    if any(i["source"] == "scan" for i in items):
        rep.msg("  ? = 摘要库里没有记录，仅从会话文件推断（可能已被清理）")
    rep.msg("  详情：agys history show <id 前缀>；搜索：agys history --search 关键词")
