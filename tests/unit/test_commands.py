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


# ---------------------------------------------------------------- 0.7 新命令

def _add_two_accounts(monkeypatch, blob_alice, blob_bob):
    _login(monkeypatch, blob_alice, "alice@gmail.com")
    assert main(["add", "alice"]) == 0
    _login(monkeypatch, blob_bob, "bob@gmail.com")
    assert main(["add", "bob"]) == 0


def test_stats_counts_switches(sandbox, monkeypatch, capsys, blob_alice, blob_bob):
    _add_two_accounts(monkeypatch, blob_alice, blob_bob)
    assert main(["use", "alice"]) == 0
    rc, out = _json(["--json", "stats"], capsys)
    assert rc == 0 and out["total_switches"] == 1
    by_id = {a["id"]: a for a in out["accounts"]}
    assert by_id["alice"]["switches"] == 1 and by_id["alice"]["current"] is True
    assert by_id["bob"]["switches"] == 0 and by_id["bob"]["current"] is False
    assert by_id["alice"]["last_switch"]


def test_prompt_outputs_current_account(sandbox, monkeypatch, capsys,
                                        blob_alice, blob_bob):
    _add_two_accounts(monkeypatch, blob_alice, blob_bob)
    rc, out = _json(["--json", "prompt"], capsys)
    assert rc == 0 and out["id"] == "bob" and out["text"] == "bob"
    rc, out = _json(["--json", "prompt", "agy:{email}"], capsys)
    assert rc == 0 and out["text"] == "agy:bob@gmail.com"
    capsys.readouterr()
    assert main(["prompt"]) == 0
    assert capsys.readouterr().out.strip() == "bob"


def test_prompt_without_accounts(sandbox, capsys):
    capsys.readouterr()
    assert main(["prompt"]) == 0
    assert capsys.readouterr().out.strip().splitlines()[-1] == "none"


def test_prompt_rejects_bad_format(sandbox, monkeypatch, capsys, blob_alice):
    _login(monkeypatch, blob_alice, "alice@gmail.com")
    assert main(["add", "alice"]) == 0
    capsys.readouterr()
    assert main(["prompt", "{oops}"]) == 1
    assert "{id}" in capsys.readouterr().err


def test_tag_add_list_remove(sandbox, monkeypatch, capsys, blob_alice, blob_bob):
    _add_two_accounts(monkeypatch, blob_alice, blob_bob)
    assert main(["tag", "alice", "work", "daily"]) == 0
    rc, out = _json(["--json", "tag"], capsys)
    assert out["tags"] == {"work": ["alice"], "daily": ["alice"]}
    rc, out = _json(["--json", "info", "alice"], capsys)
    assert sorted(out["tags"]) == ["daily", "work"]
    assert main(["tag", "alice", "--remove", "daily"]) == 0
    rc, out = _json(["--json", "tag"], capsys)
    assert out["tags"] == {"work": ["alice"]}
    # 没打标签的帐号用 --tag 选号应报错并给出指引
    capsys.readouterr()
    assert main(["auto", "--dry-run", "--tag", "personal"]) == 1
    assert "标签" in capsys.readouterr().err


def test_auto_tag_restricts_candidates(sandbox, monkeypatch, capsys,
                                       blob_alice, blob_bob):
    from agys import quota
    _add_two_accounts(monkeypatch, blob_alice, blob_bob)
    assert main(["tag", "bob", "work"]) == 0
    monkeypatch.setattr(quota, "probe", lambda acc_id, cache=None: {
        "id": acc_id, "state": "ok", "remaining": 0.5, "detail": "",
        "checked": 1, "models": [], "reset": ""})
    # 只在打了 work 标签的 bob 里选，额度更高的 alice 不参与
    rc, out = _json(["--json", "auto", "--dry-run", "--tag", "work"], capsys)
    assert rc == 0 and out["choice"] == "bob" and out["tag"] == "work"
    capsys.readouterr()
    assert main(["auto", "--no-launch", "--tag", "work"]) == 0
    assert "已切到 'bob'" in capsys.readouterr().out


def test_watch_once_warns_on_current_exhausted(sandbox, monkeypatch, capsys,
                                               blob_alice, blob_bob):
    from agys import quota as quota_mod
    _add_two_accounts(monkeypatch, blob_alice, blob_bob)
    monkeypatch.setattr(quota_mod, "snapshot", lambda v, offline=False, ids=None: [
        {"id": "alice", "state": "ok", "remaining": 0.8, "detail": "剩余 80%",
         "checked": 1, "models": [], "reset": "", "email": "alice@gmail.com"},
        {"id": "bob", "state": "exhausted", "remaining": 0.0, "detail": "429",
         "checked": 1, "models": [], "reset": "", "email": "bob@gmail.com"},
    ])
    capsys.readouterr()
    assert main(["watch", "--once"]) == 0
    captured = capsys.readouterr()
    assert "自动换号" in captured.err        # 当前帐号（bob）耗尽要有提醒
    assert "已停止监控" in captured.out


def test_watch_json_requires_once(sandbox, monkeypatch, capsys, blob_alice):
    _login(monkeypatch, blob_alice, "alice@gmail.com")
    assert main(["add", "alice"]) == 0
    capsys.readouterr()
    assert main(["--json", "watch"]) == 1
    captured = capsys.readouterr()
    assert "once" in captured.out or "--once" in captured.err


def test_info_token_expiry_warning(sandbox, monkeypatch, capsys):
    import time as time_mod
    exp = int(time_mod.time()) + 3600
    blob = (f'{{"auth_method":"oauth","token":{{"refresh_token":"X1",'
            f'"email":"a@gmail.com","expiry": {exp}}}}}').encode()
    _login(monkeypatch, blob, "a@gmail.com")
    assert main(["add", "alice"]) == 0
    rc, out = _json(["--json", "info", "alice"], capsys)
    assert rc == 0 and out["token_expiry"]
    assert abs(out["token_remaining_sec"] - 3600) < 120
    assert any("过期" in w for w in out["warnings"])


def test_doctor_warns_on_expiring_token(sandbox, monkeypatch, capsys):
    import time as time_mod
    exp = int(time_mod.time()) + 3600
    blob = (f'{{"auth_method":"oauth","token":{{"refresh_token":"X2",'
            f'"email":"b@gmail.com","expiry": {exp}}}}}').encode()
    _login(monkeypatch, blob, "b@gmail.com")
    assert main(["add", "bob"]) == 0
    rc, out = _json(["--json", "doctor"], capsys)
    assert rc == 0
    assert any("过期" in w for w in out["warnings"])
