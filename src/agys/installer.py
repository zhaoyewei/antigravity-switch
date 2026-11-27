"""免 Python 安装：预编译二进制的命名、下载 URL 与安装模式标记。

为什么单独一层：`install.sh` / `install.ps1` 负责实际下载与放置文件，
但「产物叫什么」「去哪里下」「这次装的是二进制还是源码」这两种脚本和
`agys update` 都必须一致，且需要被单测覆盖，所以抽成纯 Python 模块
（无副作用、无网络、只用标准库）。

二进制由 PyInstaller 从**同一份源码**打包（内置 Python 运行时），
用户机器上不需要安装 Python；命名不含版本号，这样安装脚本可以直接用
`releases/latest/download/<asset>` 而不用先查 API / 依赖 jq。
"""
from __future__ import annotations

import os
import platform
import sys

APP = "agys"
REPO = "antigravity-switch"
DEFAULT_OWNER = "zhaoyewei"
DEFAULT_REF = "main"


# ---------------------------------------------------------------- 平台与产物名

def platform_key(system=None):
    """把 sys.platform / uname 归一成 windows / macos / linux；未知返回空串。"""
    s = (system or sys.platform or "").lower()
    if s.startswith(("win", "mingw", "msys", "cygwin")):
        return "windows"
    if s.startswith("darwin") or "macos" in s:
        return "macos"
    if s.startswith("linux"):
        return "linux"
    return ""


def arch_key(machine=None):
    """把 CPU 架构归一成 x86_64 / arm64；未知返回空串。"""
    m = (machine or platform.machine() or "").lower()
    if m in ("x86_64", "amd64", "x64"):
        return "x86_64"
    if m in ("aarch64", "arm64"):
        return "arm64"
    return ""


def asset_name(system=None, machine=None):
    """发布产物名，例如 agys-windows-x86_64.exe / agys-linux-arm64。"""
    kind = platform_key(system)
    arch = arch_key(machine)
    if not kind or not arch:
        return ""
    suffix = ".exe" if kind == "windows" else ""
    return f"{APP}-{kind}-{arch}{suffix}"


# ---------------------------------------------------------------- URL

def _owner(owner=None):
    return owner or os.environ.get("GITHUB_OWNER") or os.environ.get(
        "AGYS_GITHUB_OWNER") or DEFAULT_OWNER


def release_asset_url(name, owner=None, ref="latest", repo=REPO):
    """`releases/latest/download/<asset>`；传 tag 时用 `releases/download/<tag>/...`。"""
    if not name:
        return ""
    base = (f"https://github.com/{_owner(owner)}/{repo}/releases/latest/download"
            if ref in ("", None, "latest")
            else f"https://github.com/{_owner(owner)}/{repo}/releases/download/{ref}")
    return f"{base}/{name}"


def installer_url(filename, owner=None, ref=None, repo=REPO):
    """raw.githubusercontent.com 上的安装脚本 URL。"""
    return (f"https://raw.githubusercontent.com/{_owner(owner)}/{repo}/"
            f"{ref or os.environ.get('AGYS_REF') or DEFAULT_REF}/{filename}")


# ---------------------------------------------------------------- 安装模式标记

def install_dir():
    return os.environ.get("AGYS_INSTALL_DIR") or os.path.join(
        os.path.expanduser("~"), ".agys")


def mode_file():
    return os.path.join(install_dir(), "install-mode")


def read_mode():
    """返回 'binary' / 'source' / ''（老版本没有标记，按源码安装处理）。"""
    try:
        with open(mode_file(), "r", encoding="utf-8") as f:
            return f.read().strip().lower()
    except OSError:
        return ""


def write_mode(mode):
    """由安装脚本调用；返回标记文件路径。"""
    p = mode_file()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write((mode or "").strip().lower() + "\n")
    return p


def update_script(mode="", system=None):
    """`agys update` 应该重新跑哪个安装脚本。

    二进制安装 + Windows → install.ps1（不需要 bash / Python）；
    其余情况沿用 install.sh（它本身会优先下载新二进制）。
    """
    if (mode or "").strip().lower() == "binary" and platform_key(system) == "windows":
        return "install.ps1"
    return "install.sh"
