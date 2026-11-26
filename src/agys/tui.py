"""极简交互式选择器（纯标准库，无第三方依赖）。

只在真终端里启用：非 TTY 时调用方应回落到普通输出或直接报错。
Windows 用 msvcrt 读键，Unix 用 termios 进 cbreak；两者都用 ANSI 序列
原地重绘，不依赖 curses（Windows 上 curses 不可用）。

设计取向：够用就好。不抢焦点、不进备用屏幕、不改终端配色，退出后
终端仍保留原有滚动内容。
"""
from __future__ import annotations

import os
import shutil
import sys


def supported() -> bool:
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False


class _Keys:
    """把两个平台的按键统一成 up/down/enter/quit/digit/other。"""

    ARROWS = {b"H": "up", b"P": "down", b"K": "left", b"M": "right"}

    def __enter__(self):
        self._fd = None
        self._old = None
        if os.name != "nt":
            import termios
            import tty
            self._fd = sys.stdin.fileno()
            self._old = termios.tcgetattr(self._fd)
            tty.setcbreak(self._fd)
        return self

    def __exit__(self, *exc):
        if self._old is not None:
            import termios
            termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old)
        return False

    def read(self) -> str:
        if os.name == "nt":
            import msvcrt
            ch = msvcrt.getwch()
            if ch in ("\x00", "\xe0"):
                return {"H": "up", "P": "down", "K": "left", "M": "right"}.get(
                    msvcrt.getwch(), "other")
            if ch in ("\r", "\n"):
                return "enter"
            if ch == "\x1b":
                return "quit"
            if ch.isdigit():
                return ch
            return "quit" if ch.lower() == "q" else "other"
        ch = sys.stdin.read(1)
        if ch == "\x1b":
            nxt = sys.stdin.read(1)
            if nxt != "[":
                return "quit"
            return {"A": "up", "B": "down"}.get(sys.stdin.read(1), "other")
        if ch in ("\r", "\n"):
            return "enter"
        if ch == "\x03":
            return "quit"
        if ch.isdigit():
            return ch
        return "quit" if ch.lower() == "q" else "other"


class _Screen:
    """原地重绘：只回退自己画过的行，绝不滚屏。"""

    def __init__(self):
        self._lines = 0

    def draw(self, lines):
        buf = ["\x1b[?25l"]
        if self._lines:
            buf.append(f"\x1b[{self._lines}A")
        for line in lines:
            buf.append("\x1b[2K" + line + "\n")
        extra = self._lines - len(lines)
        if extra > 0:
            for _ in range(extra):
                buf.append("\x1b[2K\n")
            buf.append(f"\x1b[{extra}A")
        sys.stdout.write("".join(buf))
        sys.stdout.flush()
        self._lines = len(lines)

    def close(self):
        sys.stdout.write("\x1b[?25h")
        sys.stdout.flush()


def _fit(text: str, width: int) -> str:
    """按显示宽度裁剪（中文占两列，这里用最粗略的 wcwidth 近似）。"""
    if width <= 0:
        return ""
    out, used = [], 0
    for ch in text:
        w = 2 if ord(ch) > 0x2E80 else 1
        if used + w > width:
            break
        out.append(ch)
        used += w
    return "".join(out)


def _rows(accounts, current):
    rows = []
    for acc in accounts:
        ident = acc.get("identity") or ""
        email = acc.get("email") or (ident.split(":", 1)[-1] if ident else "")
        rows.append({
            "id": acc["id"],
            "email": email or "-",
            "aliases": ", ".join(acc.get("aliases") or []),
            "identity": ident,
            "note": "当前" if acc["id"] == current else "",
        })
    return rows


def render(rows, index, current, active, title="agys 帐号切换"):
    width = shutil.get_terminal_size((72, 20)).columns
    id_w = max([len(r["id"]) for r in rows] + [8]) + 2
    mail_w = max([len(r["email"]) for r in rows] + [16]) + 2
    body = max(20, width - id_w - mail_w - 8)
    managed = {r["identity"] for r in rows if r["identity"]}
    warn = "  （未纳入管理）" if active and active not in managed else ""

    lines = ["", f"  {title}", ""]
    lines.append(f"  当前帐号   {current or '无'}"
                 f"    活跃凭据 {active or '无'}{warn}")
    lines.append("  " + "─" * max(12, min(width - 4, 60)))
    for i, row in enumerate(rows):
        mark = "▸" if i == index else " "
        tail = "  " + _fit(row["note"] or row["aliases"], body)
        lines.append(f"  {mark} {i + 1:>2}  {row['id']:<{id_w}}"
                     f"{_fit(row['email'], mail_w):<{mail_w}}{tail}".rstrip())
    lines.append("  " + "─" * max(12, min(width - 4, 60)))
    lines.append("  ↑/↓ 移动   1-9 跳转   Enter 切换   q 取消")
    return lines


def pick(accounts, current=None, active=None, title="agys 帐号切换"):
    """在终端里选一个帐号，返回 id；取消返回 None。"""
    if not accounts:
        return None
    if not supported():
        raise RuntimeError("非交互终端（stdin/stdout 不是 TTY），请显式指定帐号")

    ids = sorted(accounts)
    rows = _rows([{**accounts[i], "id": i} for i in ids], current)
    index = ids.index(current) if current in ids else 0

    screen = _Screen()
    try:
        with _Keys() as keys:
            while True:
                screen.draw(render(rows, index, current, active, title))
                key = keys.read()
                if key == "up":
                    index = (index - 1) % len(ids)
                elif key == "down":
                    index = (index + 1) % len(ids)
                elif key in "123456789" and len(key) == 1:
                    if int(key) - 1 < len(ids):
                        index = int(key) - 1
                elif key == "enter":
                    screen.draw(render(rows, index, current, active, title))
                    return ids[index]
                elif key == "quit":
                    return None
    except KeyboardInterrupt:
        return None
    finally:
        screen.close()
