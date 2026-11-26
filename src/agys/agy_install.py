"""agy 检测与自动安装。

使用 Google 官方安装脚本（见 https://antigravity.google/docs/getting-started?tab=cli）：
  macOS / Linux : curl -fsSL https://antigravity.google/cli/install.sh | bash
  Windows (PS)  : irm https://antigravity.google/cli/install.ps1 | iex
  Windows (CMD) : curl -fsSL https://antigravity.google/cli/install.cmd -o install.cmd && install.cmd && del install.cmd

可用 AGYS_AGY_INSTALL_CMD 覆盖安装命令；AGYS_NO_AUTO_INSTALL=1 关闭自动安装。
网络受限时（例如需要代理），安装失败会给出官方命令与手动安装指引，不影响已有数据。
"""
from __future__ import annotations

import os
import subprocess

from . import proxy
from .common import AgysError
from .config import IS_WIN, agy_binary, paths

DOCS_URL = "https://antigravity.google/docs/getting-started?tab=cli"

UNIX_CMD = "curl -fsSL https://antigravity.google/cli/install.sh | bash"
WIN_PS_CMD = "irm https://antigravity.google/cli/install.ps1 | iex"
WIN_CMD_CMD = ("curl -fsSL https://antigravity.google/cli/install.cmd -o install.cmd "
               "&& install.cmd && del install.cmd")

# 只有这些命令真正需要 agy 二进制；其它命令（诊断、导入导出等）不触发安装
NEEDS_AGY = frozenset({"init", "add", "use", "as", "switch", "run"})


def detect():
    """返回 (是否已安装, 位置说明)。显式指定 AGYS_AGY_BIN 时视为已配置。"""
    override = os.environ.get("AGYS_AGY_BIN")
    if override:
        return True, f"AGYS_AGY_BIN={override}"
    b = agy_binary()
    return (bool(b), b or "")


def official_commands():
    if IS_WIN:
        return [WIN_PS_CMD, WIN_CMD_CMD]
    return [UNIX_CMD]


def install_argv(proxy_url=None):
    """返回 (展示用命令, argv)。

    Windows 的 irm 不读环境变量里的代理，需要显式设置 DefaultWebProxy；
    自定义 AGYS_AGY_INSTALL_CMD 时不自动加前缀，由使用者自行处理。
    """
    override = os.environ.get("AGYS_AGY_INSTALL_CMD")
    if IS_WIN:
        cmd = override or WIN_PS_CMD
        if proxy_url and not override:
            ps = ("$p='" + proxy_url + "'; $env:HTTP_PROXY=$p; $env:HTTPS_PROXY=$p; "
                  "[System.Net.WebRequest]::DefaultWebProxy="
                  "New-Object System.Net.WebProxy($p); " + cmd)
            return cmd, ["powershell", "-NoProfile", "-Command", ps]
        return cmd, ["powershell", "-NoProfile", "-Command", cmd]
    cmd = override or UNIX_CMD
    return cmd, ["bash", "-c", cmd]


def _hint():
    cmds = official_commands()
    return ("官方安装命令：\n  " + "\n  ".join(cmds)
            + f"\n文档：{DOCS_URL}\n也可设置 AGYS_AGY_INSTALL_CMD 使用自定义安装命令，"
              "或设置 AGYS_AGY_BIN 指向已有的 agy 二进制。")


def ensure(rep, *, auto=True):
    """确保 agy 可用。返回 True 表示本次刚完成安装（布局指纹需要刷新）。"""
    ok, where = detect()
    if ok:
        return False
    if os.environ.get("AGYS_NO_AUTO_INSTALL") == "1" or not auto:
        rep.warn("未检测到 agy；运行 agys init 会自动安装。\n" + _hint())
        return False
    proxy_url = proxy.current()
    cmd, argv = install_argv(proxy_url)
    if proxy_url:
        rep.msg(f"agys: 安装过程将通过代理 {proxy.mask(proxy_url)}")
    rep.msg(f"agys: 未检测到 agy，正在使用官方安装脚本安装：\n  {cmd}")
    try:
        rc = subprocess.call(argv, timeout=300, env=proxy.child_env())
    except FileNotFoundError:
        raise AgysError("找不到安装所需的 shell（bash / powershell）。\n" + _hint())
    except subprocess.TimeoutExpired:
        raise AgysError("安装超时（5 分钟）。\n" + _hint())
    if rc != 0:
        raise AgysError(f"安装脚本返回 {rc}。\n" + _hint())
    ok2, where2 = detect()
    if not ok2:
        raise AgysError("安装脚本执行完成但仍找不到 agy（可能需要重开终端刷新 PATH）。\n" + _hint())
    rep.msg(f"agys: agy 安装成功：{where2}")
    return True


def describe():
    ok, where = detect()
    return {"installed": ok, "location": where,
            "official_commands": official_commands(), "docs": DOCS_URL}
