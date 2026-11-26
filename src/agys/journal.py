"""切换事务日志：两处写（凭据 + google_accounts.json）无法真正原子，
用加密的 pending.json 记录 before/after，崩溃后下次启动自动回滚。"""
from __future__ import annotations

import base64
import json
import os

from .config import paths
from .config import paths
from .crypto import seal, secure_dir, secure_write, unseal
from .vault import load_vault, save_vault


def _write(tx):
    p = paths()
    secure_dir(p.home)
    raw = (json.dumps(tx, ensure_ascii=False) + "\n").encode("utf-8")
    secure_write(p.pending, base64.b64encode(seal(raw)).decode("ascii").encode("ascii"))


def _read():
    try:
        with open(paths().pending, "rb") as f:
            return json.loads(unseal(base64.b64decode(f.read())).decode("utf-8"))
    except (FileNotFoundError, ValueError):
        return None
    except Exception:
        return None


def begin(*, target, before_cred, before_ga, before_current,
          after_cred, after_ga, after_current):
    _write({
        "ts": __import__("datetime").datetime.now().astimezone().isoformat(),
        "target": target,
        "before_cred": base64.b64encode(before_cred).decode("ascii") if before_cred else None,
        "after_cred": base64.b64encode(after_cred).decode("ascii"),
        "before_ga": before_ga, "after_ga": after_ga,
        "before_current": before_current, "after_current": after_current,
        "phase": "started",
    })


def set_phase(phase):
    tx = _read()
    if tx:
        tx["phase"] = phase
        _write(tx)


def finish():
    try:
        os.unlink(paths().pending)
    except FileNotFoundError:
        pass


def recover(store):
    """若存在未完成事务，保守回滚到 before 状态。返回提示文本或 None。"""
    tx = _read()
    if not tx:
        return None
    try:
        before = tx.get("before_cred")
        if before:
            store.set(base64.b64decode(before))
        else:
            store.delete()
        ga = tx.get("before_ga")
        if ga is not None:
            secure_write(paths().ga,
                         (json.dumps(ga, ensure_ascii=False) + "\n").encode("utf-8"))
        v = load_vault()
        v["current"] = tx.get("before_current")
        save_vault(v)
    except Exception as e:
        return (f"检测到上次未完成的切换事务，但自动回滚失败：{e}。"
                f"请运行 agys doctor 检查，必要时手动 agys add 重新收录。")
    finally:
        finish()
    return (f"检测到上次未完成的切换事务（目标 {tx.get('target')}），"
            f"已自动回滚到切换前状态。请重新执行切换命令。")
