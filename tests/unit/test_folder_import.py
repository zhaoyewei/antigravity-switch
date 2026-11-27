"""从「agy 用户文件夹」导入的测试：扫描 / 格式识别 / 换算 / 命令层行为。"""
import base64
import json
import os

import pytest

from agys import folderimport, vault
from agys.cli import main
from agys.credentials import get_store


# ---------------------------------------------------------------- 夹具

def _jwt(claims):
    def b(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return f"{b({'alg': 'none'})}.{b(claims)}.sig"


def write_json(path, data):
    os.makedirs(os.path.dirname(str(path)), exist_ok=True)
    with open(str(path), "w", encoding="utf-8") as f:
        f.write(data if isinstance(data, str) else json.dumps(data))


def agy_blob(email="usera@example.com", refresh="RT-A",
             expiry="2030-01-02T03:04:05.000000Z"):
    return {"token": {"access_token": _jwt({"email": email}), "token_type": "Bearer",
                      "refresh_token": refresh, "expiry": expiry},
            "auth_method": "oauth"}


def oauth_creds(email="usera@example.com", refresh="RT-A", expiry_date=1790000000000):
    return {"access_token": _jwt({"email": email}), "refresh_token": refresh,
            "token_type": "Bearer", "expiry_date": expiry_date,
            "id_token": _jwt({"email": email}), "scope": "openid email"}


def make_folder(root, name, files):
    """files: {相对路径: dict 或 字符串}"""
    d = os.path.join(str(root), name)
    os.makedirs(d, exist_ok=True)
    for rel, data in files.items():
        write_json(os.path.join(d, rel), data)
    return d


# ---------------------------------------------------------------- 扫描与识别

def test_scan_agy_blob_keeps_payload(tmp_path):
    d = make_folder(tmp_path, "userA", {
        "google_accounts.json": {"active": "usera@example.com", "old": []},
        "agy-credential.json": agy_blob(),
    })
    found = folderimport.scan(d)
    assert found.kind == "agy-blob"
    assert found.email == "usera@example.com"
    assert found.identity == "email:usera@example.com"
    blob = json.loads(found.blob.decode("utf-8"))
    assert blob["auth_method"] == "oauth"
    assert blob["token"]["refresh_token"] == "RT-A"
    assert found.ga["active"] == "usera@example.com"


def test_scan_oauth_creds_converted_to_agy_shape(tmp_path):
    d = make_folder(tmp_path, "userA", {"oauth_creds.json": oauth_creds()})
    found = folderimport.scan(d)
    assert found.kind == "oauth-creds"
    blob = json.loads(found.blob.decode("utf-8"))
    # 关键：字段映射与 agy 凭据库里的形态一致（顶层顺序 token -> auth_method）
    assert list(blob) == ["token", "auth_method"]
    assert blob["auth_method"] == "oauth"
    assert list(blob["token"]) == ["access_token", "token_type", "refresh_token", "expiry"]
    assert blob["token"]["refresh_token"] == "RT-A"
    assert blob["token"]["expiry"] == "2026-09-21T14:13:20.000000Z"   # epoch 毫秒 → ISO
    # 没有 google_accounts.json 时，邮箱从 id_token 的 JWT 里取
    assert found.email == "usera@example.com"
    assert found.identity == "email:usera@example.com"


def test_scan_linux_token_file_nested(tmp_path):
    d = make_folder(tmp_path, "userB", {
        "antigravity-cli/antigravity-oauth-token": agy_blob(email="userb@example.com",
                                                            refresh="RT-B"),
    })
    found = folderimport.scan(d)
    assert found.kind == "agy-blob"
    assert found.email == "userb@example.com"
    assert found.source.endswith("antigravity-oauth-token")


def test_scan_prefers_agy_blob_over_oauth_creds(tmp_path):
    d = make_folder(tmp_path, "userC", {
        "oauth_creds.json": oauth_creds(email="userc@example.com"),
        "agy-credential.json": agy_blob(email="userc@example.com", refresh="RT-C"),
    })
    found = folderimport.scan(d)
    assert found.kind == "agy-blob"
    assert json.loads(found.blob.decode())["token"]["refresh_token"] == "RT-C"
    assert len(found.others) == 1 and "oauth_creds.json" in found.others[0]


def test_scan_empty_folder_explains_what_is_needed(tmp_path):
    d = make_folder(tmp_path, "empty", {"settings.json": {"theme": "dark"}})
    with pytest.raises(folderimport.FolderImportError) as e:
        folderimport.scan(d)
    msg = str(e.value)
    assert "没找到可用的 agy 登录凭据" in msg
    assert "oauth_creds.json" in msg and "antigravity-oauth-token" in msg


def test_scan_only_google_accounts_is_not_enough(tmp_path):
    d = make_folder(tmp_path, "onlyga", {"google_accounts.json": {"active": "a@b.c"}})
    with pytest.raises(folderimport.FolderImportError) as e:
        folderimport.scan(d)
    assert "google_accounts.json" in str(e.value)


def test_scan_hints_when_folder_holds_an_export_file(tmp_path):
    d = make_folder(tmp_path, "exported", {
        "agys-export.json": {"format": "agys-export", "version": 2,
                             "accounts": [{"id": "x", "credential_b64": "eA=="}]},
    })
    with pytest.raises(folderimport.FolderImportError) as e:
        folderimport.scan(d)
    assert "直接导入它：agys import" in str(e.value)


def test_scan_not_a_directory(tmp_path):
    with pytest.raises(folderimport.FolderImportError):
        folderimport.scan(str(tmp_path / "nope"))


@pytest.mark.parametrize("raw,expected", [
    (1790000000000, "2026-09-21T14:13:20.000000Z"),          # epoch 毫秒
    (1790000000, "2026-09-21T14:13:20.000000Z"),             # epoch 秒
    ("2030-01-02T03:04:05.000000Z", "2030-01-02T03:04:05.000000Z"),   # 已是 ISO
    (None, ""),
])
def test_expiry_normalisation(raw, expected):
    data = {} if raw is None else {"expiry_date": raw}
    assert folderimport._expiry_iso(data) == expected


# ---------------------------------------------------------------- 命令层

def _folder(tmp_path, name="userA", **kw):
    return make_folder(tmp_path, name, {
        "google_accounts.json": {"active": "usera@example.com", "old": []},
        "oauth_creds.json": oauth_creds(**kw),
    })


def test_import_folder_registers_account_without_switching(sandbox, tmp_path, capsys):
    d = _folder(tmp_path)
    assert main(["import", d]) == 0
    v = vault.load_vault()
    assert list(v["accounts"]) == ["usera"]
    assert v["accounts"]["usera"]["email"] == "usera@example.com"
    assert v["current"] is None
    assert get_store().get() is None          # 没切换：活跃凭据不动
    out = capsys.readouterr().out
    assert "agys use usera" in out


def test_import_folder_custom_name_and_json(sandbox, tmp_path, capsys):
    d = _folder(tmp_path)
    capsys.readouterr()
    assert main(["--json", "import", d, "--name", "work"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True and payload["id"] == "work"
    assert payload["kind"] == "oauth-creds"
    assert payload["updated"] is False
    assert "work" in vault.load_vault()["accounts"]


def test_import_folder_use_switches(sandbox, tmp_path, capsys):
    d = _folder(tmp_path)
    assert main(["import", d, "--use"]) == 0
    prof = vault.load_profile("usera")
    assert get_store().get() == prof["blob"]        # 活跃凭据已被写成该帐号
    assert vault.load_vault()["current"] == "usera"


def test_import_folder_dry_run_touches_nothing(sandbox, tmp_path, capsys):
    d = _folder(tmp_path)
    capsys.readouterr()
    assert main(["--json", "import", d, "--dry-run"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True and payload["exists"] is False
    assert vault.load_vault()["accounts"] == {}
    assert get_store().get() is None


def test_import_folder_twice_updates_same_identity(sandbox, tmp_path, capsys):
    d = _folder(tmp_path)
    assert main(["import", d, "--name", "usera"]) == 0
    capsys.readouterr()
    # 换一个 id 再导一次：同一身份应更新已有帐号，而不是造出两个一样的号
    assert main(["--json", "import", d, "--name", "other"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["id"] == "usera" and payload["updated"] is True
    assert list(vault.load_vault()["accounts"]) == ["usera"]


def test_import_folder_conflict_rename_keeps_both(sandbox, tmp_path, capsys):
    d = _folder(tmp_path)
    assert main(["import", d, "--name", "usera"]) == 0
    assert main(["import", d, "--name", "usera", "--on-conflict", "rename"]) == 0
    assert sorted(vault.load_vault()["accounts"]) == ["usera", "usera-2"]


def test_import_folder_conflict_skip_keeps_old_credential(sandbox, tmp_path, capsys):
    d = _folder(tmp_path, refresh="RT-FIRST")
    assert main(["import", d, "--name", "usera"]) == 0
    before = vault.load_profile("usera")["blob"]
    d2 = _folder(tmp_path, name="userA2", refresh="RT-SECOND")
    assert main(["import", d2, "--name", "usera", "--on-conflict", "skip"]) == 0
    assert vault.load_profile("usera")["blob"] == before
    out = capsys.readouterr().out
    assert "skip" in out


def test_import_folder_reports_missing_credential(sandbox, tmp_path, capsys):
    d = make_folder(tmp_path, "empty", {"settings.json": {"a": 1}})
    assert main(["import", d]) == 1
    err = capsys.readouterr().err
    assert "没找到可用的 agy 登录凭据" in err
    assert vault.load_vault()["accounts"] == {}
