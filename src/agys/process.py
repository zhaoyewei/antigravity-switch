"""运行中进程检测与托管：列出 PID、可选一键关闭、切换后尽力重开。"""
from __future__ import annotations

import csv
import json
import locale
import os
import subprocess
from dataclasses import dataclass, asdict

from . import proxy
from .config import IS_WIN, agy_argv, paths
from .crypto import secure_dir, secure_write


@dataclass
class Proc:
    pid: int
    name: str
    title: str = ""
    cmd: str = ""


def _names():
    return [s.strip() for s in paths().process_names.split(",") if s.strip()]


def _decode(raw) -> str:
    """子进程输出解码。

    不能依赖 text=True：PYTHONUTF8=1 或 Python 3.15+ 默认 UTF-8 模式时，
    Windows 的 tasklist 输出（本地代码页）会在 reader 线程里解码失败。
    """
    if not raw:
        return ""
    for enc in ("utf-8", locale.getpreferredencoding(False), "gbk", "cp1252"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", "replace")


def list_procs():
    """返回进程列表；检测工具不可用返回 None。"""
    names = _names()
    if not names:
        return []
    try:
        if IS_WIN:
            r = subprocess.run(["tasklist", "/FO", "CSV", "/NH", "/V"],
                               capture_output=True, timeout=20)
            if r.returncode != 0:
                return None
            out = []
            for row in csv.reader(_decode(r.stdout).splitlines()):
                if len(row) < 2:
                    continue
                name, pid = row[0].strip(), row[1].strip()
                title = row[8].strip() if len(row) > 8 else ""
                if name.lower() in [n.lower() for n in names]:
                    try:
                        out.append(Proc(int(pid), name, title))
                    except ValueError:
                        continue
            return out
        out = []
        for n in names:
            r = subprocess.run(["pgrep", "-x", n], capture_output=True, timeout=15)
            if r.returncode != 0:
                continue
            for line in _decode(r.stdout).split():
                try:
                    pid = int(line)
                except ValueError:
                    continue
                ps = subprocess.run(["ps", "-p", str(pid), "-o", "args="],
                                    capture_output=True, timeout=10)
                out.append(Proc(pid, n, "", _decode(ps.stdout).strip()))
        return out
    except Exception:
        return None


def close_all(procs):
    """关闭列出的进程，返回成功关闭数量。"""
    killed = 0
    for pr in procs:
        try:
            if IS_WIN:
                r = subprocess.run(["taskkill", "/PID", str(pr.pid), "/T", "/F"],
                                   capture_output=True, timeout=15)
                if r.returncode == 0:
                    killed += 1
            else:
                os.kill(pr.pid, 15)
                killed += 1
        except Exception:
            continue
    return killed


def save_reopen(procs):
    if not procs:
        return
    secure_dir(paths().home)
    secure_write(paths().reopen, (json.dumps(
        [asdict(p) for p in procs], ensure_ascii=False) + "\n").encode("utf-8"))


def reopen_previous():
    """尽力重开被关闭的 agy CLI 窗口；IDE 只能提示手动重开。返回提示文本。"""
    try:
        with open(paths().reopen, "r", encoding="utf-8") as f:
            rows = json.load(f)
    except (FileNotFoundError, ValueError):
        return ""
    try:
        os.unlink(paths().reopen)
    except OSError:
        pass
    cmd = agy_argv()
    cli = [r for r in rows if "antigravity" not in r.get("name", "").lower()]
    ide = [r for r in rows if "antigravity" in r.get("name", "").lower()]
    n = 0
    for r in cli:
        if not cmd:
            break
        try:
            subprocess.Popen(cmd, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             env=proxy.child_env())
            n += 1
        except Exception:
            pass
    msgs = []
    if n:
        msgs.append(f"已重开 {n} 个 agy 窗口（原命令行参数无法还原，以默认方式启动）")
    elif cli:
        msgs.append(f"有 {len(cli)} 个 agy 窗口未能自动重开，请手动启动")
    if ide:
        msgs.append(f"检测到 {len(ide)} 个 Antigravity IDE 进程，请手动重新打开 IDE")
    return "；".join(msgs)


def describe(procs):
    if not procs:
        return "无"
    return ", ".join(f"{p.name}(pid={p.pid})" for p in procs)
