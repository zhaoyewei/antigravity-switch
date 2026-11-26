import json
import os
import sqlite3

import pytest

from agys import history


def _mk_summary_db(gemini, rows):
    base = os.path.join(str(gemini), "antigravity-cli")
    os.makedirs(base, exist_ok=True)
    p = os.path.join(base, "conversation_summaries.db")
    conn = sqlite3.connect(p)
    conn.execute(
        "create table conversation_summaries (conversation_id text, title text,"
        " preview text, step_count integer, last_modified_time datetime,"
        " workspace_uris text, project_id text, status text)")
    conn.executemany(
        "insert into conversation_summaries values (?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()
    return base


def _mk_conv(base, cid, steps):
    d = os.path.join(base, "conversations")
    os.makedirs(d, exist_ok=True)
    conn = sqlite3.connect(os.path.join(d, f"{cid}.db"))
    conn.execute("create table steps (idx integer primary key, step_type integer,"
                 " status integer, render_info blob, step_payload blob)")
    conn.executemany("insert into steps values (?,?,?,?,?)", steps)
    conn.commit()
    conn.close()


def test_extract_text_skips_protobuf_noise():
    blob = b"\x08\x01\x12\x0f\xe5\xa6\x82\xe4\xbd\x95\xe5\xae\x89\xe8\xa3\x85skills"
    out = history.extract_text(blob, minlen=4)
    assert any("如何安装skills" in t for t in out)


def test_looks_natural_rejects_code_fragments():
    assert history._looks_natural("如何让你拥有 codex 一样的体验？")
    assert history._looks_natural("Search for codex")
    assert not history._looks_natural('AbsolutePath":"C:/x/SKILL.md","too')
    assert not history._looks_natural("8873181f-802f-4ed7-a82e-a4e41cb4a4de")
    assert not history._looks_natural("DZQͽ}?@淎2P")


def test_collect_and_search(sandbox):
    base = _mk_summary_db(sandbox["gemini"], [
        ("cid-1", "", "论文构思", 12, "2026-07-18 02:28:54.5439492+00:00",
         '["file:///C:/Users/zhao"]', "p", ""),
        ("cid-2", "标题二", "", 3, "2026-07-19 10:00:00+00:00",
         '["file:///D:/work"]', "p", ""),
    ])
    _mk_conv(base, "cid-1", [
        (0, 14, 0, None, b"\x12\x0e\xe5\xa6\x82\xe4\xbd\x95\xe5\xae\x89\xe8\xa3\x85"),
        (1, 8, 0, None, b"\x12\x10List references dir"),
    ])
    items = history.collect()
    assert [i["id"] for i in items] == ["cid-2", "cid-1"]
    assert items[1]["title"] == "论文构思"
    assert items[1]["updated"] == "2026-07-18 02:28:54"

    assert [i["id"] for i in history.collect(search="标题二")] == ["cid-2"]
    assert [i["id"] for i in history.collect(workspace="D:/work")] == ["cid-2"]
    assert len(history.collect(limit=1)) == 1


def test_orphan_conversation_appears_and_can_be_hidden(sandbox):
    base = _mk_summary_db(sandbox["gemini"], [])
    _mk_conv(base, "orphan-1", [
        (0, 14, 0, None, b"\x12\x0e\xe5\xa6\x82\xe4\xbd\x95\xe5\xae\x89\xe8\xa3\x85"),
    ])
    items = history.collect()
    assert len(items) == 1 and items[0]["source"] == "scan"
    assert history.collect(include_orphans=False) == []


def test_show_returns_steps(sandbox):
    base = _mk_summary_db(sandbox["gemini"], [
        ("cid-9", "标题", "", 2, "2026-07-18 02:28:54+00:00", "[]", "", ""),
    ])
    _mk_conv(base, "cid-9", [
        (0, 14, 0, None, b"\x12\x0e\xe5\xa6\x82\xe4\xbd\x95\xe5\xae\x89\xe8\xa3\x85"),
        (1, 8, 0, None, b"\x12\x10Search for codex"),
    ])
    hits, row = history.find("cid-9")
    assert row and row["id"] == "cid-9"
    steps = history.read_steps("cid-9")
    assert [s["idx"] for s in steps] == [0, 1]
    assert steps[1]["excerpt"] == "Search for codex"


def test_find_by_prefix_ambiguity(sandbox):
    _mk_summary_db(sandbox["gemini"], [
        ("abc-1", "a", "", 1, "2026-07-18 02:00:00+00:00", "[]", "", ""),
        ("abc-2", "b", "", 1, "2026-07-18 03:00:00+00:00", "[]", "", ""),
    ])
    hits, row = history.find("abc")
    assert row is None and len(hits) == 2
    hits, row = history.find("abc-2")
    assert row and row["title"] == "b"


def test_available_false_without_dir(sandbox):
    assert history.available() is False
    assert history.overview() is None


def test_export_payload_and_markdown(sandbox):
    base = _mk_summary_db(sandbox["gemini"], [
        ("cid-3", "导出测试", "", 1, "2026-07-18 02:28:54+00:00", "[]", "", ""),
    ])
    _mk_conv(base, "cid-3", [(0, 14, 0, None, b"\x12\x10Search for codex")])
    items = history.collect()
    payload = history.build_export(items, details=True)
    assert payload["count"] == 1
    assert payload["conversations"][0]["steps_detail"][0]["excerpt"]
    md = history.render_markdown(payload)
    assert "导出测试" in md and "所有帐号共用" in md
    json.dumps(payload)  # 必须可序列化


def test_cli_history_list_show_export(sandbox, capsys):
    from agys.cli import main

    base = _mk_summary_db(sandbox["gemini"], [
        ("cid-1", "", "论文构思", 2, "2026-07-18 02:28:54+00:00",
         '["file:///C:/Users/zhao"]', "", ""),
    ])
    _mk_conv(base, "cid-1", [
        (0, 14, 0, None, b"\x12\x10Search for codex"),
        (1, 8, 0, None, b"\x12\x0e\xe5\xa6\x82\xe4\xbd\x95\xe5\xae\x89\xe8\xa3\x85"),
    ])

    capsys.readouterr()
    assert main(["history"]) == 0
    out = capsys.readouterr().out
    assert "所有帐号共用" in out and "论文构思" in out

    assert main(["history", "show", "cid-1"]) == 0
    out = capsys.readouterr().out
    assert "Search for codex" in out

    target = str(sandbox["home"] / "hist.json")
    assert main(["history", "export", target]) == 0
    with open(target, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["count"] == 1 and data["conversations"][0]["id"] == "cid-1"

    target_md = str(sandbox["home"] / "hist.md")
    assert main(["history", "export", target_md, "--format", "md", "--detail"]) == 0
    assert "论文构思" in open(target_md, encoding="utf-8").read()


def test_cli_history_without_agy_dir(sandbox, capsys):
    from agys.cli import main
    capsys.readouterr()
    assert main(["history"]) == 1
    assert "没找到 agy 会话目录" in capsys.readouterr().err
