import json

from agys.cli import main
from agys.credentials import get_store
from agys import expimp, journal, vault


def _login(monkeypatch, blob, email):
    monkeypatch.setenv("AGYS_STUB_BLOB", blob.decode("utf-8"))
    monkeypatch.setenv("AGYS_STUB_EMAIL", email)


def _json(main_args, capsys):
    capsys.readouterr()
    rc = main(main_args)
    out = capsys.readouterr().out
    return rc, json.loads(out)


def test_add_switch_and_current(sandbox, monkeypatch, capsys, blob_alice, blob_bob):
    _login(monkeypatch, blob_alice, "alice@gmail.com")
    assert main(["add"]) == 0
    _login(monkeypatch, blob_bob, "bob@gmail.com")
    assert main(["add", "bob"]) == 0

    rc, out = _json(["--json", "list"], capsys)
    assert rc == 0 and len(out["accounts"]) == 2 and out["current"] == "bob"

    assert main(["use", "alice"]) == 0
    assert get_store().get() == blob_alice
    rc, out = _json(["--json", "current"], capsys)
    assert rc == 0 and out["consistent"] is True
    assert out["active_identity"] == "email:alice@gmail.com"


def test_layout_change_refused_unless_allowed(sandbox, monkeypatch, capsys,
                                               blob_alice, blob_bob):
    _login(monkeypatch, blob_alice, "alice@gmail.com")
    assert main(["add", "alice"]) == 0
    _login(monkeypatch, blob_bob, "bob@gmail.com")
    assert main(["add", "bob"]) == 0
    monkeypatch.setenv("AGYS_CRED_TARGET", "gemini:changed")
    capsys.readouterr()
    assert main(["use", "alice"]) == 1
    assert "存储布局变化" in capsys.readouterr().err
    assert main(["use", "alice", "--allow-layout-change"]) == 0


def test_alias_and_resolve(sandbox, monkeypatch, capsys, blob_alice):
    _login(monkeypatch, blob_alice, "alice@gmail.com")
    assert main(["add", "alice"]) == 0
    assert main(["alias", "alice", "work", "primary"]) == 0
    rc, out = _json(["--json", "list"], capsys)
    assert rc == 0 and "work" in out["accounts"][0]["aliases"]
    assert main(["use", "work"]) == 0
    assert get_store().get() == blob_alice


def test_remove_requires_confirm(sandbox, monkeypatch, capsys, blob_alice):
    _login(monkeypatch, blob_alice, "alice@gmail.com")
    assert main(["add", "alice"]) == 0
    capsys.readouterr()
    assert main(["remove", "alice"]) == 1
    assert "需要显式 --yes" in capsys.readouterr().err
    assert main(["remove", "alice", "--yes"]) == 0
    assert get_store().get() is None
    assert vault.load_vault()["current"] is None


def test_export_import_checksum(sandbox, monkeypatch, capsys, blob_alice):
    _login(monkeypatch, blob_alice, "alice@gmail.com")
    assert main(["add", "alice"]) == 0
    assert main(["export"]) == 0
    path = expimp.default_path()
    data = json.loads(open(path, encoding="utf-8").read())
    data["accounts"][0]["email"] = "evil@x.com"
    open(path, "w", encoding="utf-8").write(json.dumps(data))
    capsys.readouterr()
    assert main(["import", path]) == 1
    assert "校验和" in capsys.readouterr().err
    assert main(["import", path, "--no-verify"]) == 0


def test_journal_recovered_on_startup(sandbox, monkeypatch, capsys, blob_alice, blob_bob):
    _login(monkeypatch, blob_alice, "alice@gmail.com")
    assert main(["add", "alice"]) == 0
    store = get_store()
    journal.begin(target="ghost", before_cred=blob_alice,
                  before_ga={"active": "alice@gmail.com", "old": []},
                  before_current="alice", after_cred=blob_bob,
                  after_ga={"active": "bob@gmail.com", "old": []},
                  after_current="ghost")
    store.set(blob_bob)
    capsys.readouterr()
    assert main(["version"]) == 0
    assert "回滚" in capsys.readouterr().err
    assert store.get() == blob_alice


def test_doctor_json(sandbox, capsys):
    rc, out = _json(["--json", "doctor"], capsys)
    assert rc == 0 and out["ok"] is True
    assert "profiles" in out and "warnings" in out
