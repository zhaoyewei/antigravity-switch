"""迁移类命令：export / import（含 agy 用户文件夹）/ backup / restore。"""
from __future__ import annotations

import datetime
import os
import shutil
import sys
import tarfile
import tempfile
import time

from .. import APP, audit, expimp, folderimport, identity
from ..common import AgysError, SwitchLock, confirm
from ..config import paths
from ..crypto import secure_dir
from ..runtime import switch_to
from ..vault import (
    email_slug, find_by_identity, save_profile, save_vault, slugify,
)


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


def _folder_dry_run(args, rep, found, acc_id, email, existing, policy):
    expiry = identity.token_expiry(found.blob)
    rep.msg(f"{APP}: 扫描 {args.path}（{found.files_seen} 个文件）")
    rep.msg(f"  凭据来源  {found.source}")
    rep.msg(f"  形态      {found.kind_label}")
    rep.msg(f"  邮箱      {email or '-'}")
    rep.msg(f"  身份      {found.identity}")
    rep.msg(f"  过期时间  {expiry or '未标注'}")
    if existing:
        rep.msg(f"  将写入    已有帐号 '{existing}'（同一身份，按 --on-conflict {policy} 处理）")
    else:
        rep.msg(f"  将导入为  '{acc_id}'")
    for other in found.others:
        rep.msg(f"  未采用    {other}")
    rep.msg("  --dry-run：没有写入任何东西")
    rep.set(dry_run=True, id=existing or acc_id, email=email, identity=found.identity,
            source=found.source, kind=found.kind, exists=bool(existing))


def _import_folder(args, rep, store, v):
    """把 agy 用户文件夹里的登录态纳管成帐号（不重新走浏览器登录）。"""
    try:
        found = folderimport.scan(args.path)
    except folderimport.FolderImportError as e:
        raise AgysError(str(e))

    email = found.email or identity.email_of(found.identity)
    acc_id = slugify(getattr(args, "name", None) or email_slug(email)
                     or identity.short(found.identity))
    policy = getattr(args, "on_conflict", "overwrite")
    # 同一份登录态可能已经用别的 id 在库里：先按身份找，避免出现两个相同的号
    same_ident = find_by_identity(found.identity, v) if found.identity else None
    existing = acc_id if acc_id in v["accounts"] else same_ident
    if getattr(args, "dry_run", False):
        _folder_dry_run(args, rep, found, acc_id, email, existing, policy)
        return

    target = acc_id
    updated = False
    with SwitchLock():
        if existing:
            if policy == "skip":
                rep.msg(f"{APP}: 帐号 '{existing}' 已存在，按 skip 保留现有凭据")
                rep.set(skipped=[existing], id=existing)
                return
            if policy == "ask" and not _ask_conflict(existing, {"email": email}, v, args):
                rep.msg(f"{APP}: 已跳过 '{existing}'")
                rep.set(skipped=[existing], id=existing)
                return
            if policy == "rename":
                target = _unique_acc_id(acc_id, v["accounts"])
            else:
                target = existing
                updated = True
        meta = {"email": email, "aliases": [], "identity": found.identity}
        save_profile(target, found.blob, found.ga, meta)
        v["accounts"][target] = {"id": target, **meta}
        save_vault(v)
        audit.log("import", result="ok",
                  detail=f"folder {args.path} -> {target} ({found.kind})")

    rep.msg(f"{APP}: 已{'更新' if updated else '从文件夹导入'}帐号 '{target}'"
            + (f"（{email}）" if email else "") + f"，凭据形态：{found.kind_label}"
            + (f"，来源 {found.source}" if not updated else "（同一身份的凭据已刷新）"))
    expiry = identity.token_expiry(found.blob)
    age = identity.expiry_age(expiry)
    if age is not None and age <= 0:
        rep.warn(f"该凭据已过期（{identity.expiry_human(expiry)}）；切换后 agy 会用 "
                 "refresh token 自动刷新，仍失败请重新 agys add 登录")
    for other in found.others:
        rep.msg(f"{APP}: 提示：同一个文件夹里还发现了 {other}，本次未采用"
                "（一次只导一个帐号，需要的话把那个目录单独再导一次）")
    rep.set(id=target, email=email, identity=found.identity, source=found.source,
            kind=found.kind, updated=updated)

    if getattr(args, "use", False):
        with SwitchLock():
            switch_to(target, args, rep, store, v)
    else:
        rep.msg(f"{APP}: 导入不会自动切换，需要时运行：agys use {target}"
                "（或给 import 加 --use）")


def cmd_import(args, rep, store, v):
    """导入：文件 = agys 导出文件；文件夹 = 已有的 agy 用户目录（免登录）。"""
    if os.path.isdir(os.path.expanduser(args.path)):
        return _import_folder(args, rep, store, v)
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
