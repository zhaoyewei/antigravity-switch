"""CLI 公共工具（供 cli.py 与 extra.py 共用，避免循环导入）。"""
from __future__ import annotations

import json
import os
import sys

from . import APP
from .config import paths
from .crypto import secure_dir, secure_write


class AgysError(Exception):
    pass


class Reporter:
    def __init__(self, as_json=False):
        self.as_json = as_json
        self.obj = {}

    def msg(self, text):
        if not self.as_json:
            print(text)

    def set(self, **kw):
        self.obj.update(kw)

    def warn(self, text):
        print(f"{APP}: 警告：{text}", file=sys.stderr)
        self.obj.setdefault("warnings", []).append(text)

    def done(self):
        if self.as_json:
            print(json.dumps({"ok": True, **self.obj}, ensure_ascii=False, indent=2))


class SwitchLock:
    def __enter__(self):
        p = paths()
        secure_dir(p.home)
        self.f = open(p.lock, "a+")
        try:
            if os.name == "nt":
                import msvcrt
                self.f.seek(0)
                msvcrt.locking(self.f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.f.close()
            raise AgysError("另一个 agys 操作正在进行（~/.agy-accounts/.switch.lock）")
        return self

    def __exit__(self, *exc):
        try:
            if os.name == "nt":
                import msvcrt
                self.f.seek(0)
                msvcrt.locking(self.f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.f.fileno(), fcntl.LOCK_UN)
        finally:
            self.f.close()
        return False


def read_ga():
    try:
        with open(paths().ga, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return None


def write_ga(ga):
    if ga is None:
        ga = {"active": "", "old": []}
    secure_write(paths().ga, (json.dumps(ga, ensure_ascii=False) + "\n").encode("utf-8"))


def confirm(prompt, yes):
    if yes:
        return True
    if not sys.stdin.isatty():
        raise AgysError(f"{prompt}：非交互终端需要显式 --yes 确认")
    try:
        return input(f"{prompt} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False
