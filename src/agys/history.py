"""agy 会话历史读取（只读）。

关键事实：agy 的本地历史**本来就不按帐号分区**。会话存在
`~/.gemini/antigravity-cli/` 下——

    conversation_summaries.db   会话列表：标题 / 步数 / 时间 / workspace
    conversations/<uuid>.db     单会话轨迹：steps 表，正文是 protobuf blob
    history.jsonl               输入行历史
    brain/<uuid>/               推理中间产物

这些文件里没有任何 account / email / user 字段，云端也只有
streamGenerateContent、没有会话列表接口。所以登录 A 帐号时看到的历史里，
本来就混着 B、C 帐号产生的会话——不需要「混起来」，它一直是共享的。

这里只做只读解析：不改任何 agy 文件，也不碰凭据。
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from pathlib import Path
from urllib.parse import quote

from .config import paths

SUMMARY_DB = "conversation_summaries.db"
CONV_DIR = "conversations"

# protobuf blob 里只有字符串是明文，其余是长度前缀和 tag
_TEXT_RUN = re.compile(r"[^\x00-\x08\x0b\x0c\x0e-\x1f\x7f]+")
_UUID_ANY = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}", re.I)
_JUNK = re.compile(r"^[A-Za-z0-9+/=_\-]{24,}$")
_SYSTEM_NOISE = re.compile(r"EPHEMERAL_MESSAGE|<[A-Z_]{4,}>")
_CJK = re.compile(r"[\u4e00-\u9fff]")
_LEAD_JUNK = re.compile(r"^[^\w\u4e00-\u9fff]+")


def base_dir() -> str:
    return os.path.join(paths().gemini_home, "antigravity-cli")


def available() -> bool:
    return os.path.isdir(base_dir())


def _connect(path):
    """只读打开；失败返回 None（被占用或不合法时不要炸掉整个命令）。"""
    try:
        uri = "file:" + quote(Path(path).as_posix(), safe="/:") + "?mode=ro"
        return sqlite3.connect(uri, uri=True, timeout=3)
    except sqlite3.Error:
        return None


def _table_columns(conn, table):
    try:
        return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
    except sqlite3.Error:
        return []


def extract_text(blob, minlen=6, maxlen=400):
    """从 protobuf blob 里捞出可读字符串（尽力而为，不保证是完整正文）。"""
    if not blob:
        return []
    try:
        raw = bytes(blob)
    except (TypeError, ValueError):
        return []
    s = raw.decode("utf-8", "ignore")
    out = []
    for m in _TEXT_RUN.finditer(s):
        t = m.group(0).strip()
        t = _LEAD_JUNK.sub("", t).strip()
        if len(t) >= minlen:
            out.append(t[:maxlen])
    return out


_SYMBOLS = re.compile(r"[{}<>|@#$%^&*=\\/~`]")


def _looks_natural(text: str) -> bool:
    """判断一段 protobuf 残留字符串像不像人写的（而不是编码碎片/JSON 参数）。"""
    t = text.strip()
    if not t or _UUID_ANY.search(t) or _JUNK.match(t):
        return False
    if t.startswith(("{", "[", "C:\\", "file:", "<", "/")):
        return False
    if t.count('"') > 2 or '":' in t:          # JSON / protobuf 结构残留
        return False
    if len(_SYMBOLS.findall(t)) / len(t) > 0.08:
        return False
    readable = sum(1 for ch in t if ch.isalnum() or ch.isspace())
    if _CJK.search(t):
        return len(t) >= 4 and readable / len(t) >= 0.6
    return len(t) >= 8 and " " in t and readable / len(t) >= 0.7


def _best_excerpt(blobs, minlen=6):
    """取一段最能代表该步骤的文字：优先中文，其次第一条像样的。"""
    cands = []
    for blob in blobs:
        for t in extract_text(blob, minlen=minlen):
            if _looks_natural(t) and not _SYSTEM_NOISE.search(t):
                cands.append(t)
    if not cands:
        return ""
    cjk = [t for t in cands if _CJK.search(t)]
    return (cjk or cands)[0]


def _normalize_time(value):
    if not value:
        return ""
    text = str(value).strip()
    # agy 存的是 .NET 风格 "2026-07-18 02:28:54.5439492+00:00"
    m = re.match(r"^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})", text)
    return f"{m.group(1)} {m.group(2)}" if m else text[:19]


def read_summaries():
    """读会话列表库。字段缺失时按空值处理，不假设 schema 固定。"""
    p = os.path.join(base_dir(), SUMMARY_DB)
    if not os.path.isfile(p):
        return []
    conn = _connect(p)
    if conn is None:
        return []
    try:
        cols = set(_table_columns(conn, "conversation_summaries"))
        if "conversation_id" not in cols:
            return []

        def pick(name, default="''"):
            return name if name in cols else f"{default} as {name}"

        sql = ("select conversation_id, "
               + pick("title") + ", "
               + pick("preview") + ", "
               + pick("step_count", "0") + ", "
               + pick("last_modified_time") + ", "
               + pick("workspace_uris") + ", "
               + pick("project_id") + ", "
               + pick("status") + " "
               "from conversation_summaries")
        out = []
        for row in conn.execute(sql):
            cid = row[0]
            if not cid:
                continue
            try:
                ws = json.loads(row[5]) if row[5] else []
            except ValueError:
                ws = [row[5]] if row[5] else []
            out.append({
                "id": cid,
                "title": (row[1] or "").strip() or (row[2] or "").strip(),
                "preview": (row[2] or "").strip(),
                "steps": int(row[3] or 0),
                "updated": _normalize_time(row[4]),
                "workspace": [str(x) for x in ws if x],
                "project": row[6] or "",
                "status": (row[7] or "").strip(),
                "source": "summary",
            })
        return out
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def scan_conversations():
    """扫 conversations/ 目录，补齐摘要库里没有的孤立会话。"""
    d = os.path.join(base_dir(), CONV_DIR)
    if not os.path.isdir(d):
        return {}
    out = {}
    for name in os.listdir(d):
        if not name.endswith(".db"):
            continue
        full = os.path.join(d, name)
        cid = name[:-3]
        steps, title = 0, ""
        conn = _connect(full)
        if conn is not None:
            try:
                steps = conn.execute("select count(*) from steps").fetchone()[0]
                for (payload,) in conn.execute(
                        "select step_payload from steps order by idx limit 4"):
                    title = _best_excerpt([payload], minlen=4)
                    if title:
                        break
            except sqlite3.Error:
                pass
            finally:
                conn.close()
        try:
            mtime = os.path.getmtime(full)
        except OSError:
            mtime = 0
        out[cid] = {"path": full, "size": os.path.getsize(full) if os.path.isfile(full) else 0,
                    "mtime": mtime, "steps": steps, "title": title}
    return out


def collect(search=None, workspace=None, limit=None, include_orphans=True):
    """合并摘要库与目录扫描结果，按最后修改时间倒序。"""
    rows = {s["id"]: s for s in read_summaries()}
    scanned = scan_conversations()
    import datetime
    for cid, info in scanned.items():
        if cid in rows:
            rows[cid]["path"] = info["path"]
            rows[cid]["size"] = info["size"]
            continue
        if not include_orphans:
            continue
        ts = ""
        if info["mtime"]:
            ts = datetime.datetime.fromtimestamp(info["mtime"]).strftime("%Y-%m-%d %H:%M:%S")
        rows[cid] = {
            "id": cid,
            "title": info["title"] or "(未命名会话)",
            "preview": "",
            "steps": info["steps"],
            "updated": ts,
            "workspace": [],
            "project": "",
            "status": "orphan",
            "source": "scan",
            "path": info["path"],
            "size": info["size"],
        }
    items = list(rows.values())
    if workspace:
        needle = workspace.replace("\\", "/").lower().rstrip("/")
        items = [i for i in items
                 if any(needle in w.replace("\\", "/").lower() for w in i["workspace"])
                 or needle in i["id"].lower()]
    if search:
        q = search.lower()

        def hit(i):
            hay = " ".join([i["id"], i["title"], i["preview"], i["project"],
                            " ".join(i["workspace"])]).lower()
            return q in hay
        items = [i for i in items if hit(i)]
    items.sort(key=lambda i: (i["updated"], i["id"]), reverse=True)
    if limit:
        items = items[:limit]
    return items


def find(cid, include_orphans=True):
    prefix = cid.lower()
    items = collect(include_orphans=include_orphans)
    for i in items:
        if i["id"] == cid:
            return [], i
    hits = [i for i in items if i["id"].lower().startswith(prefix)]
    return hits, (hits[0] if len(hits) == 1 else None)


def _conv_path(cid):
    return os.path.join(base_dir(), CONV_DIR, f"{cid}.db")


def read_steps(cid, limit=None):
    """读一个会话的步骤轨迹。正文是 protobuf，只能给可读摘要。"""
    p = _conv_path(cid)
    if not os.path.isfile(p):
        return []
    conn = _connect(p)
    if conn is None:
        return []
    try:
        cols = set(_table_columns(conn, "steps"))
        if not cols:
            return []
        render = "render_info" if "render_info" in cols else "null"
        payload = "step_payload" if "step_payload" in cols else "null"
        if "step_type" not in cols or "idx" not in cols:
            return []
        status = "status" if "status" in cols else "0"
        sql = (f"select idx, step_type, {status}, {render}, {payload} "
               "from steps order by idx")
        out = []
        for idx, stype, stat, rinfo, pdata in conn.execute(sql):
            excerpt = _best_excerpt([rinfo, pdata], minlen=6)
            out.append({"idx": idx, "type": stype, "status": stat,
                        "excerpt": excerpt})
            if limit and len(out) >= limit:
                break
        return out
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def overview():
    """给 status/doctor 用的一句话概览。"""
    if not available():
        return None
    items = collect(limit=None)
    orphan = sum(1 for i in items if i["source"] == "scan")
    return {"total": len(items), "orphan": orphan,
            "latest": items[0]["updated"] if items else ""}


def build_export(items, details=False, max_steps=40):
    payload = {"tool": "agys", "kind": "history", "count": len(items),
               "note": "agy 本地历史不按帐号分区；本文件为只读导出", "conversations": []}
    for i in items:
        row = dict(i)
        if details:
            row["steps_detail"] = read_steps(i["id"], limit=max_steps)
        payload["conversations"].append(row)
    return payload


def render_markdown(payload) -> str:
    lines = ["# agy 会话历史", "",
             f"共 {payload['count']} 个会话。agy 本地历史不按帐号分区，"
             "所有帐号共用同一份。", ""]
    for c in payload["conversations"]:
        lines.append(f"## {c['title'] or '(未命名会话)'}")
        lines.append("")
        lines.append(f"- id: `{c['id']}`")
        lines.append(f"- 时间: {c['updated'] or '-'}    步数: {c['steps']}")
        if c["workspace"]:
            lines.append(f"- workspace: {', '.join(c['workspace'])}")
        if c.get("status"):
            lines.append(f"- 状态: {c['status']}")
        for st in c.get("steps_detail") or []:
            if st.get("excerpt"):
                lines.append(f"    - [{st['idx']}] {st['excerpt'][:160]}")
        lines.append("")
    return "\n".join(lines) + "\n"
