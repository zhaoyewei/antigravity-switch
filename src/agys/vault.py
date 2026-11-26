"""vault 与 profile 存储（含 v0.1 明文格式兼容与渐进迁移）。"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import time

from . import identity
from .config import paths
from .crypto import CryptoError, seal, secure_dir, secure_write, unseal

SCHEMA = 2


def now_iso():
    import datetime
    return datetime.datetime.now().astimezone().replace(microsecond=0).isoformat()


def slugify(s):
    s = (s or "").strip().lower()
    out = "".join(ch if (ch.isalnum() or ch in "-_") else "-" for ch in s)
    return out.strip("-") or f"account-{int(time.time())}"


def email_slug(email):
    local = (email or "").split("@")[0].strip()
    return slugify(local) if local else ""


def default_vault():
    return {"version": SCHEMA, "accounts": {}, "current": None, "layout": None}


def load_vault():
    p = paths()
    try:
        with open(p.vault, "r", encoding="utf-8") as f:
            v = json.load(f)
    except (FileNotFoundError, ValueError):
        return default_vault()
    if not isinstance(v, dict):
        return default_vault()
    v.setdefault("version", 1)
    v.setdefault("accounts", {})
    v.setdefault("current", None)
    v.setdefault("layout", None)
    if not isinstance(v["accounts"], dict):
        v["accounts"] = {}
    for acc, meta in v["accounts"].items():
        meta.setdefault("id", acc)
        meta.setdefault("email", "")
        meta.setdefault("aliases", [])
        meta.setdefault("identity", "")
    return v


def save_vault(v):
    secure_dir(paths().home)
    v["version"] = SCHEMA
    secure_write(paths().vault,
                 (json.dumps(v, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def profile_path(acc_id):
    return os.path.join(paths().profiles, acc_id, "profile.json")


def save_profile(acc_id, blob: bytes, ga, meta):
    p = paths()
    secure_dir(os.path.join(p.profiles, acc_id))
    ident = meta.get("identity") or identity.extract(blob, ga)
    prof = {
        "schema": SCHEMA,
        "id": acc_id,
        "email": meta.get("email") or identity.email_of(ident),
        "aliases": meta.get("aliases") or [],
        "identity": ident,
        "created": meta.get("created") or now_iso(),
        "updated": now_iso(),
        "sealed_blob": base64.b64encode(seal(bytes(blob))).decode("ascii"),
        "google_accounts": ga,
    }
    secure_write(profile_path(acc_id),
                 (json.dumps(prof, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    return prof


def load_profile(acc_id):
    try:
        with open(profile_path(acc_id), "r", encoding="utf-8") as f:
            prof = json.load(f)
    except (FileNotFoundError, ValueError):
        raise KeyError(acc_id)
    if prof.get("schema") == SCHEMA:
        try:
            prof["blob"] = unseal(base64.b64decode(prof["sealed_blob"]))
        except (KeyError, ValueError, CryptoError) as e:
            raise CryptoError(f"帐号 '{acc_id}' 的凭据无法解密：{e}")
    else:
        # v0.1 明文格式
        text = prof.get("blob", "")
        try:
            prof["blob"] = (base64.b64decode(text) if prof.get("blob_b64")
                            else text.encode("utf-8"))
        except Exception:
            prof["blob"] = b""
        prof.setdefault("email", "")
        prof.setdefault("aliases", [])
        prof["identity"] = identity.extract(prof["blob"], prof.get("google_accounts"))
    return prof


def migrate_profiles():
    """把 v0.1 明文 profile 就地升级为加密格式。返回迁移数量。"""
    p = paths()
    if not os.path.isdir(p.profiles):
        return 0
    n = 0
    for acc in os.listdir(p.profiles):
        fp = profile_path(acc)
        if not os.path.isfile(fp):
            continue
        try:
            with open(fp, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, ValueError):
            continue
        if raw.get("schema") == SCHEMA:
            continue
        try:
            prof = load_profile(acc)
            save_profile(acc, prof["blob"], prof.get("google_accounts"), prof)
            n += 1
        except Exception:
            continue
    return n


def resolve(name, v=None):
    v = v or load_vault()
    n = (name or "").strip().lower()
    exact = []
    for acc, meta in v["accounts"].items():
        keys = [acc.lower(), (meta.get("email") or "").lower()]
        keys += [a.lower() for a in (meta.get("aliases") or [])]
        if meta.get("identity"):
            keys.append(meta["identity"].lower())
            keys.append(identity.short(meta["identity"]))
        if n in keys:
            exact.append(acc)
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise KeyError(f"'{name}' 匹配到多个帐号：{', '.join(exact)}，请用 id 精确指定")
    pref = [acc for acc in v["accounts"] if acc.lower().startswith(n)]
    if len(pref) == 1:
        return pref[0]
    if not v["accounts"]:
        raise KeyError("当前没有任何帐号，请先运行：agys add")
    raise KeyError(f"找不到帐号 '{name}'，现有帐号见 agys list")


def find_by_identity(ident: str, v=None):
    v = v or load_vault()
    for acc in v["accounts"]:
        try:
            if load_profile(acc).get("identity") == ident:
                return acc
        except (KeyError, CryptoError):
            continue
    return None


def delete_profile_dir(acc_id):
    d = os.path.join(paths().profiles, acc_id)
    if os.path.isdir(d):
        shutil.rmtree(d)
