"""命令实现（commands 包）与命令别名的单元测试。"""
import json
import os
import urllib.request

from agys import __version__, vault
from agys.cli import main
from agys.common import write_ga
from agys.credentials import get_store


def _login(monkeypatch, blob, email):
    monkeypatch.setenv("AGYS_STUB_BLOB", blob.decode("utf-8"))
    monkeypatch.setenv("AGYS_STUB_EMAIL", email)


def _json(main_args, capsys):
    capsys.readouterr()
    rc = main(main_args)
    out = capsys.readouterr().out
    return rc, json.loads(out)


def _add_two(sandbox, monkeypatch, blob_alice, blob_bob):
    _login(monkeypatch, blob_alice, "alice@gmail.com")
    assert main(["add", "alice"]) == 0
    _login(monkeypatch, blob_bob, "bob@gmail.com")
    assert main(["add", "bob"]) == 0
    return sandbox


def test_status_whoami_ids(sandbox, monkeypatch, capsys, blob_alice):
    _login(monkeypatch, blob_alice, "alice@gmail.com")
    assert main(["add", "alice"]) == 0
    rc, out = _json(["--json", "status"], capsys)
    assert rc == 0 and out["accounts"] == 1 and out["consistent"] is True
    rc, out = _json(["--json", "whoami"], capsys)
    assert rc == 0 and out["email"] == "alice@gmail.com"
    rc, out = _json(["--json", "ids"], capsys)
    assert rc == 0 and "alice" in out["ids"]


def test_init_adopts_current_login(sandbox, monkeypatch, capsys, blob_alice):
    get_store().set(blob_alice)
    write_ga({"active": "alice@gmail.com", "old": []})
    rc, out = _json(["--json", "init"], capsys)
    assert rc == 0 and out["logged_in"] is True and out["accounts"] == 1
    assert "alice" in vault.load_vault()["accounts"]


def test_logout_keeps_accounts(sandbox, monkeypatch, capsys, blob_alice):
    _login(monkeypatch, blob_alice, "alice@gmail.com")
    assert main(["add", "alice"]) == 0
    rc, out = _json(["--json", "logout"], capsys)
    assert rc == 0 and out["logged_out"] is True
    assert get_store().get() is None
    v = vault.load_vault()
    assert v["current"] is None and "alice" in v["accounts"]
    capsys.readouterr()
    assert main(["whoami"]) == 1


def test_info_defaults_to_current(sandbox, monkeypatch, capsys, blob_alice, blob_bob):
    _add_two(sandbox, monkeypatch, blob_alice, blob_bob)
    rc, out = _json(["--json", "info"], capsys)
    assert rc == 0 and out["id"] == "bob" and out["is_default"] is False
    rc, out = _json(["--json", "info", "alice"], capsys)
    assert rc == 0 and out["credential_bytes"] == len(blob_alice)


def test_default_and_use_without_name(sandbox, monkeypatch, capsys,
                                      blob_alice, blob_bob):
    _add_two(sandbox, monkeypatch, blob_alice, blob_bob)
    assert main(["default", "alice"]) == 0
    rc, out = _json(["--json", "default"], capsys)
    assert rc == 0 and out["default"] == "alice"
    # 非交互 / --json 下省略帐号，应回落到默认帐号
    rc, out = _json(["--json", "use"], capsys)
    assert rc == 0 and out["current"] == "alice"
    assert get_store().get() == blob_alice
    rc, out = _json(["--json", "info", "alice"], capsys)
    assert out["is_default"] is True


def test_completion_and_help(sandbox, capsys):
    rc, out = _json(["--json", "completion", "bash"], capsys)
    assert rc == 0 and "_agys_complete" in out["script"]
    rc, out = _json(["--json", "completion", "fish"], capsys)
    assert rc == 0 and "__fish_use_subcommand" in out["script"]
    rc, out = _json(["--json", "help"], capsys)
    assert rc == 0 and "commands" in out["topics"]
    rc, out = _json(["--json", "help", "security"], capsys)
    assert rc == 0 and "安全模型" in out["text"]


def test_check_offline(sandbox, monkeypatch, capsys):
    def boom(*args, **kwargs):
        raise OSError("offline")
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    rc, out = _json(["--json", "check"], capsys)
    assert rc == 0 and out["current"] == __version__ and out["latest"] is None


def test_doctor_fix_and_backup_restore(sandbox, monkeypatch, capsys, blob_alice):
    _login(monkeypatch, blob_alice, "alice@gmail.com")
    assert main(["add", "alice"]) == 0

    rc, out = _json(["--json", "doctor", "--fix"], capsys)
    assert rc == 0 and "fixes" in out

    backup = os.path.join(str(sandbox["home"]), "unit-backup.tar.gz")
    rc, out = _json(["--json", "backup", backup], capsys)
    assert rc == 0 and os.path.isfile(backup) and out["size"] > 0

    assert main(["remove", "alice", "--yes"]) == 0
    assert "alice" not in vault.load_vault()["accounts"]
    rc, out = _json(["--json", "restore", backup, "--yes"], capsys)
    assert rc == 0 and out["restored"] is True
    assert "alice" in vault.load_vault()["accounts"]


def test_command_aliases(sandbox, monkeypatch, capsys, blob_alice):
    _login(monkeypatch, blob_alice, "alice@gmail.com")
    assert main(["add", "alice"]) == 0
    assert main(["alias", "alice", "work"]) == 0
    rc, out = _json(["--json", "ls"], capsys)
    assert rc == 0 and out["current"] == "alice"
    assert main(["switch", "work"]) == 0
    assert get_store().get() == blob_alice
    assert main(["rm", "alice", "--yes"]) == 0
    assert "alice" not in vault.load_vault()["accounts"]
