"""迁移类命令：export / import / backup / restore。"""
from __future__ import annotations

import datetime
import os
import shutil
import sys
import tarfile
import tempfile
import time

from .. import APP, audit, expimp, identity
from ..common import AgysError, SwitchLock, confirm
from ..config import paths
from ..crypto import secure_dir
from ..vault import save_profile, save_vault, slugify


# ---------------------------------------------------------------- export

def cmd_export(args, rep, store, v):
    if not v["accounts"]:
        raise AgysError("没有任何帐号可导出")
    path = args.path or expimp.default_path()
    out = expimp.write_export(path, v)
    rep.msg(f"{APP}: 已导出 {len(out['accounts'])} 个帐号到 {path}")
    rep.msg(f"{APP}: 注意：文件内含明文登录凭据，请妥善保管、迁移完成后删除。")
    rep.msg(f"{APP}: {expimp.NOTE}")
    rep.set(path=path, count=len(out["accounts"]), checksum=out["checksum"])


# ---------------------------------------------------------------- import

def _unique_acc_id(base, accounts):
    """rename 策略下找一个不冲突的 id：alice -> alice-2 -> alice-3 ..."""
    if base not in accounts:
        return base
    n = 2
    while f"{base}-{n}" in accounts:
        n += 1
    return f"{base}-{n}"


def _ask_conflict(acc_id, incoming, v, args):
    if getattr(args, "yes", False):
        return True
    if not sys.stdin.isatty():
        raise AgysError(
            f"帐号 '{acc_id}' 已存在，而 --on-conflict ask 在非交互终端下无法提问。"
            "改用 skip / overwrite / rename，或加 --yes 表示全部覆盖。")
    cur = v["accounts"][acc_id]
    answer = input(f"帐号 '{acc_id}' 已存在（现有 {cur.get('email') or '-'} → "
                   f"导入 {incoming.get('email') or '-'}），覆盖？[y/N] ")
    return answer.strip().lower() in ("y", "yes")


def cmd_import(args, rep, store, v):
    accounts, warns = expimp.read_import(args.path, verify=not args.no_verify)
    policy = getattr(args, "on_conflict", "overwrite")
    with SwitchLock():
        added, updated, skipped, renamed = [], [], [], []
        for a in accounts:
            acc_id = slugify(a.get("id") or "")
            if not acc_id:
                continue
            blob = expimp.account_blob(a)
            ga = a.get("google_accounts")
            ident = a.get("identity") or identity.extract(blob, ga)
            meta = {"email": a.get("email") or identity.email_of(ident),
                    "aliases": a.get("aliases") or [], "identity": ident,
                    "created": a.get("created") or ""}
            existed = acc_id in v["accounts"]
            target = acc_id
            if existed:
                if policy == "skip":
                    skipped.append(acc_id)
                    continue
                if policy == "ask" and not _ask_conflict(acc_id, a, v, args):
                    skipped.append(acc_id)
                    continue
                if policy == "rename":
                    target = _unique_acc_id(acc_id, v["accounts"])
            save_profile(target, blob, ga, meta)
            v["accounts"][target] = {"id": target, **meta}
            if not existed:
                added.append(target)
            elif target == acc_id:
                updated.append(acc_id)
            else:
                renamed.append(f"{acc_id}->{target}")
        save_vault(v)
        audit.log("import", result="ok",
                  detail=f"{len(added)} new, {len(updated)} updated, "
                         f"{len(skipped)} skipped, {len(renamed)} renamed ({policy})")
        for w in warns:
            rep.warn(w)
        parts = [f"新导入 {len(added)} 个", f"更新 {len(updated)} 个"]
        if skipped:
            parts.append(f"跳过 {len(skipped)} 个")
        if renamed:
            parts.append("重命名 " + ", ".join(renamed))
        rep.msg(f"{APP}：" + "、".join(parts) + "；导入不会自动切换，用 agys use <id> 切换")
        rep.set(added=added, updated=updated, skipped=skipped, renamed=renamed,
                on_conflict=policy)


# ---------------------------------------------------------------- backup

def cmd_backup(args, rep, store, v):
    home = paths().home
    path = args.path or os.path.join(
        home, "backups",
        f"agys-backup-{datetime.date.today().isoformat()}-{int(time.time())}.tar.gz")
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    skip_dirs = {"backups", "__pycache__"}
    skip_files = {".switch.lock", "pending.json", "memory_credential.json"}
    with tarfile.open(path, "w:gz") as tar:
        for root, dirs, files in os.walk(home):
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            for f in files:
                if f in skip_files or f == os.path.basename(path):
                    continue
                full = os.path.join(root, f)
                tar.add(full, arcname=os.path.relpath(full, home))
    rep.msg(f"{APP}: 已备份到 {path}")
    rep.msg(f"{APP}: 注意：备份内含加密后的登录凭据与密钥，请按敏感文件保管。")
    rep.set(path=path, size=os.path.getsize(path))


def cmd_restore(args, rep, store, v):
    if not os.path.isfile(args.path):
        raise AgysError(f"备份文件不存在：{args.path}")
    if not confirm(f"恢复备份将覆盖当前 vault 与帐号数据（{args.path}）", args.yes):
        raise AgysError("已取消")
    tmp = tempfile.mkdtemp(prefix="agys-restore-")
    try:
        with tarfile.open(args.path, "r:gz") as tar:
            members = [m for m in tar.getmembers()
                       if not os.path.isabs(m.name) and ".." not in m.name.split("/")
                       and m.isfile()]
            try:
                tar.extractall(tmp, members=members, filter="data")
            except TypeError:
                # Python < 3.12 没有 filter 参数；members 已做路径校验
                tar.extractall(tmp, members=members)
        if not os.path.isfile(os.path.join(tmp, "vault.json")):
            raise AgysError("备份中缺少 vault.json，拒绝恢复")
        home = paths().home
        secure_dir(home)
        with SwitchLock():
            for name in ("vault.json", "audit.jsonl", ".vault.key"):
                src = os.path.join(tmp, name)
                if os.path.isfile(src):
                    shutil.copy2(src, os.path.join(home, name))
            src_prof = os.path.join(tmp, "profiles")
            if os.path.isdir(src_prof):
                os.makedirs(os.path.join(home, "profiles"), exist_ok=True)
                for acc in os.listdir(src_prof):
                    s = os.path.join(src_prof, acc)
                    if os.path.isdir(s):
                        shutil.copytree(s, os.path.join(home, "profiles", acc),
                                        dirs_exist_ok=True)
        audit.log("restore", result="ok", detail=os.path.basename(args.path))
        rep.msg(f"{APP}: 已从 {args.path} 恢复。"
                f"请运行 agys use <id> 让活跃凭据与恢复后的 vault 对齐。")
        rep.set(restored=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
