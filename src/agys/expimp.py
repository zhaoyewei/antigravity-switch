"""导出 / 导入。

导出文件保持明文（用户决定），但默认落在 ~/.agy-accounts/exports/，
并带 schema 版本与 SHA-256 校验和，防止被误提交或篡改。
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from datetime import date

from .config import paths
from .crypto import CryptoError, secure_dir, secure_write
from .vault import load_profile, now_iso

NOTE = ("迁移用途：refresh token 会被 Google 轮换。导入新机器后请在源机器 "
        "agys remove 或停止使用，避免两台机器互相踢掉登录。")


def _canonical(accounts):
    return json.dumps(accounts, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")


def build_export(vault):
    accounts = []
    for acc in sorted(vault["accounts"]):
        try:
            prof = load_profile(acc)
        except (KeyError, CryptoError):
            continue
        accounts.append({
            "id": prof["id"],
            "email": prof.get("email") or "",
            "aliases": prof.get("aliases") or [],
            "identity": prof.get("identity") or "",
            "created": prof.get("created") or "",
            "credential_b64": base64.b64encode(prof["blob"]).decode("ascii"),
            "google_accounts": prof.get("google_accounts"),
        })
    return {
        "format": "agys-export",
        "version": 2,
        "exported_at": now_iso(),
        "note": NOTE,
        "accounts": accounts,
        "checksum": hashlib.sha256(_canonical(accounts)).hexdigest(),
    }


def default_path():
    return os.path.join(paths().exports, f"agys-export-{date.today().isoformat()}.json")


def write_export(path, vault):
    out = build_export(vault)
    secure_dir(os.path.dirname(os.path.abspath(path)))
    secure_write(path, (json.dumps(out, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    return out


def read_import(path, verify=True):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, ValueError) as e:
        raise ValueError(f"无法读取导入文件：{e}")
    if not isinstance(data, dict) or data.get("format") != "agys-export":
        raise ValueError("不是有效的 agys 导出文件（缺少 format: agys-export 标记）")
    accounts = data.get("accounts")
    if not isinstance(accounts, list) or not accounts:
        raise ValueError("导出文件中没有帐号数据")
    warnings = []
    if data.get("version") != 2:
        warnings.append(f"导出文件版本为 {data.get('version')}，按兼容模式导入")
    expected = data.get("checksum")
    if expected:
        actual = hashlib.sha256(_canonical(accounts)).hexdigest()
        if actual != expected:
            if verify:
                raise ValueError("校验和不匹配：文件可能被篡改或损坏（--no-verify 可强制导入）")
            warnings.append("校验和不匹配，已按 --no-verify 强制导入")
    elif verify:
        warnings.append("该文件没有校验和（v0.1 导出），已按兼容模式导入")
    return accounts, warnings


def account_blob(a):
    if a.get("credential_b64"):
        return base64.b64decode(a["credential_b64"])
    text = a.get("blob", "")
    return base64.b64decode(text) if a.get("blob_b64") else text.encode("utf-8")
