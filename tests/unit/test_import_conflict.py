import json

from agys import expimp, vault
from agys.cli import main


def _export_two(sandbox, blob_alice):
    v = vault.load_vault()
    v["accounts"]["alice"] = {"id": "alice", "email": "alice@gmail.com",
                              "aliases": [], "identity": "email:alice@gmail.com"}
    vault.save_profile("alice", blob_alice, {"active": "alice@gmail.com", "old": []},
                       {"email": "alice@gmail.com"})
    vault.save_vault(v)
    path = str(sandbox["home"] / "e.json")
    expimp.write_export(path, v)
    return path


def _login(monkeypatch, blob, email):
    monkeypatch.setenv("AGYS_STUB_BLOB", blob.decode("utf-8"))
    monkeypatch.setenv("AGYS_STUB_EMAIL", email)


def test_import_overwrite_is_default(sandbox, monkeypatch, capsys, blob_alice, blob_bob):
    path = _export_two(sandbox, blob_alice)
    _login(monkeypatch, blob_bob, "bob@gmail.com")
    assert main(["add"]) == 0
    capsys.readouterr()
    assert main(["import", path]) == 0
    out = capsys.readouterr().out
    assert "更新 1 个" in out
    v = vault.load_vault()
    assert v["accounts"]["alice"]["email"] == "alice@gmail.com"


def test_import_skip_keeps_existing(sandbox, monkeypatch, capsys, blob_alice, blob_bob):
    path = _export_two(sandbox, blob_alice)
    _login(monkeypatch, blob_bob, "bob@gmail.com")
    assert main(["add"]) == 0
    # 把已有 alice 改成别的邮箱，导入时 skip 应保留现值
    v = vault.load_vault()
    v["accounts"]["alice"] = {"id": "alice", "email": "keep@old.com",
                              "aliases": [], "identity": ""}
    vault.save_vault(v)
    capsys.readouterr()
    assert main(["import", path, "--on-conflict", "skip"]) == 0
    out = capsys.readouterr().out
    assert "跳过 1 个" in out
    assert vault.load_vault()["accounts"]["alice"]["email"] == "keep@old.com"


def test_import_rename_creates_new_id(sandbox, monkeypatch, capsys,
                                      blob_alice, blob_bob):
    path = _export_two(sandbox, blob_alice)
    _login(monkeypatch, blob_bob, "bob@gmail.com")
    assert main(["add"]) == 0
    capsys.readouterr()
    assert main(["import", path, "--on-conflict", "rename"]) == 0
    out = capsys.readouterr().out
    assert "alice->alice-2" in out
    v = vault.load_vault()
    assert "alice" in v["accounts"] and "alice-2" in v["accounts"]
    # 再导一次应继续往后排号
    capsys.readouterr()
    assert main(["import", path, "--on-conflict", "rename"]) == 0
    assert "alice-3" in vault.load_vault()["accounts"]


def test_import_ask_without_tty_errors(sandbox, monkeypatch, capsys,
                                       blob_alice, blob_bob):
    path = _export_two(sandbox, blob_alice)
    _login(monkeypatch, blob_bob, "bob@gmail.com")
    assert main(["add"]) == 0
    capsys.readouterr()
    assert main(["import", path, "--on-conflict", "ask"]) == 1
    assert "--on-conflict ask" in capsys.readouterr().err


def test_import_ask_with_yes_overwrites(sandbox, monkeypatch, capsys,
                                        blob_alice, blob_bob):
    path = _export_two(sandbox, blob_alice)
    _login(monkeypatch, blob_bob, "bob@gmail.com")
    assert main(["add"]) == 0
    capsys.readouterr()
    assert main(["import", path, "--on-conflict", "ask", "--yes"]) == 0
    assert "更新 1 个" in capsys.readouterr().out


def test_import_json_reports_policy(sandbox, monkeypatch, capsys,
                                    blob_alice, blob_bob):
    path = _export_two(sandbox, blob_alice)
    _login(monkeypatch, blob_bob, "bob@gmail.com")
    assert main(["add"]) == 0
    capsys.readouterr()
    assert main(["--json", "import", path, "--on-conflict", "skip"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["on_conflict"] == "skip" and out["skipped"] == ["alice"]
