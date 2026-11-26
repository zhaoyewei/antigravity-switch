import json

import pytest

from agys import expimp, vault


def _setup(v, blob, email, acc="alice"):
    v["accounts"][acc] = {"id": acc, "email": email, "aliases": [], "identity": ""}
    vault.save_profile(acc, blob, {"active": email, "old": []}, {"email": email})


def test_export_checksum_and_roundtrip(sandbox, blob_alice):
    v = vault.load_vault()
    _setup(v, blob_alice, "alice@gmail.com")
    vault.save_vault(v)
    out = expimp.write_export(str(sandbox["home"] / "e.json"), v)
    assert out["version"] == 2 and len(out["accounts"]) == 1
    accounts, warns = expimp.read_import(str(sandbox["home"] / "e.json"))
    assert not warns
    assert expimp.account_blob(accounts[0]) == blob_alice


def test_tampered_checksum_rejected(sandbox, blob_alice):
    v = vault.load_vault()
    _setup(v, blob_alice, "alice@gmail.com")
    vault.save_vault(v)
    p = sandbox["home"] / "e.json"
    expimp.write_export(str(p), v)
    data = json.loads(p.read_text(encoding="utf-8"))
    data["accounts"][0]["email"] = "hacked@evil.com"
    p.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="校验和"):
        expimp.read_import(str(p))
    accounts, warns = expimp.read_import(str(p), verify=False)
    assert warns and len(accounts) == 1


def test_v1_export_compat(sandbox, blob_alice):
    p = sandbox["home"] / "v1.json"
    p.write_text(json.dumps({
        "format": "agys-export", "version": 1,
        "accounts": [{"id": "legacy", "email": "l@x.com",
                      "blob": blob_alice.decode(), "blob_b64": False,
                      "google_accounts": {"active": "l@x.com"}}],
    }), encoding="utf-8")
    accounts, warns = expimp.read_import(str(p))
    assert warns and expimp.account_blob(accounts[0]) == blob_alice


def test_default_path_inside_agy_home(sandbox):
    assert str(sandbox["home"]) in expimp.default_path()
