"""网络相关命令：proxy（只影响 agys 启动的子进程，不改系统代理）。"""
from __future__ import annotations

import os

from .. import APP, proxy
from ..common import AgysError
from ..config import paths


def cmd_proxy(args, rep, store, v):
    sub = getattr(args, "proxy_cmd", None) or "show"

    if sub == "set":
        url = proxy.set_proxy(args.url, args.no_proxy)
        entries = proxy.no_proxy_entries()
        rep.msg(f"{APP}: 已设置代理 {proxy.mask(url)}（写入 {paths().config_file}）")
        rep.msg(f"{APP}: NO_PROXY = {','.join(entries)}")
        ok, detail = proxy.test(url)
        if ok:
            rep.msg(f"{APP}: 连通性检测通过：{detail}")
        else:
            rep.warn(f"连通性检测失败：{detail}（配置已保存；代理可能尚未启动）")
        rep.set(proxy=proxy.mask(url), reachable=ok,
                no_proxy=",".join(entries), config=paths().config_file)
        return

    if sub == "clear":
        proxy.clear_proxy()
        rep.msg(f"{APP}: 已清除代理配置；agys 不再注入，agy 将继承父进程原有的网络设置")
        rep.set(proxy=None)
        return

    if sub == "test":
        ok, detail = proxy.test(args.url)
        rep.set(ok=ok, detail=detail, proxy=proxy.mask(proxy.current() or ""))
        if not ok:
            raise AgysError(f"代理不可用：{detail}")
        rep.msg(f"{APP}: {detail}")
        return

    url = proxy.current()
    entries = proxy.no_proxy_entries()
    source = "config" if url else "none"
    if url and os.environ.get("AGYS_PROXY"):
        source = "env:AGYS_PROXY"
    rep.set(proxy=proxy.mask(url or ""), source=source,
            no_proxy=",".join(entries), config=paths().config_file)
    if not url:
        if os.environ.get("AGYS_NO_PROXY") == "1":
            rep.msg(f"{APP}: 本次已通过 AGYS_NO_PROXY=1 禁用代理注入")
        rep.msg(f"{APP}: 未配置代理（agy 将直连或走系统网络设置）")
        rep.msg(f"{APP}: 设置示例：agys proxy set http://127.0.0.1:7890")
        return
    rep.msg(f"{APP}: 代理 {proxy.mask(url)}（来源：{source}）")
    rep.msg(f"       NO_PROXY = {','.join(entries)}")
    rep.msg("       作用范围：agys add / as / auto / update 启动的 agy、agy 安装脚本，"
            "以及 agys 自身的额度探测与版本检查")
