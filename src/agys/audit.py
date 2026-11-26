"""切换审计日志（JSONL，仅记录元数据，不记录 token）。"""
from __future__ import annotations

import json
import os

from .config import paths
from .crypto import secure_dir, secure_write
from .vault import now_iso


def log(action, *, from_id=None, to_id=None, result="ok", detail=""):
    p = paths()
    secure_dir(p.home)
    entry = {"ts": now_iso(), "action": action, "from": from_id,
             "to": to_id, "result": result, "detail": detail}
    line = (json.dumps(entry, ensure_ascii=False) + "\n").encode("utf-8")
    try:
        with open(p.audit, "ab") as f:
            f.write(line)
    except OSError:
        return
    try:
        os.chmod(p.audit, 0o600)
    except OSError:
        pass


def read(limit=20):
    try:
        with open(paths().audit, "r", encoding="utf-8") as f:
            lines = f.readlines()[-limit:]
    except FileNotFoundError:
        return []
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out
