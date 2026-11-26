import json

from agys import vault
from agys.credentials import get_store


def test_profile_roundtrip(sandbox, blob_alice):
    ga = {"active": "alice@gmail.com", "old": []}
    prof = vault.save_profile("alice", blob_alice, ga, {"email": "alice@gmail.com"})
    assert prof["schema"] == vault.SCHEMA
    loaded = vault.load_profile("alice")
    assert loaded["blob"] == blob_alice
    assert loaded["identity"] == "email:alice@gmail.com"
    assert "sealed_blob" in json.loads(
        open(vault.profile_path("alice"), encoding="utf-8").read())


def test_v1_plaintext_migration(sandbox, blob_alice):
    d = sandbox["home"] / "profiles" / "legacy"
    d.mkdir(parents=True)
    (d / "profile.json").write_text(json.dumps({
        "id": "legacy", "email": "legacy@gmail.com", "aliases": [],
        "blob": blob_alice.decode(), "blob_b64": False,
        "google_accounts": {"active": "legacy@gmail.com", "old": []},
    }), encoding="utf-8")
    assert vault.load_profile("legacy")["blob"] == blob_alice
    assert vault.migrate_profiles() >= 1
    raw = json.loads((d / "profile.json").read_text(encoding="utf-8"))
    assert raw["schema"] == vault.SCHEMA and "sealed_blob" in raw
    assert vault.load_profile("legacy")["blob"] == blob_alice


def test_resolve_by_alias_email_prefix(sandbox, blob_alice):
    v = vault.default_vault()
    v["accounts"] = {
        "alice-work": {"id": "alice-work", "email": "alice@gmail.com",
                       "aliases": ["work", "primary"], "identity": "email:alice@gmail.com"},
    }
    assert vault.resolve("work", v) == "alice-work"
    assert vault.resolve("ALICE@GMAIL.COM", v) == "alice-work"
    assert vault.resolve("alice-", v) == "alice-work"


def test_find_by_identity(sandbox, blob_alice):
    vault.save_profile("alice", blob_alice, {"active": "alice@gmail.com"}, {})
    v = vault.load_vault()
    v["accounts"]["alice"] = {"id": "alice", "email": "alice@gmail.com", "aliases": []}
    vault.save_vault(v)
    assert vault.find_by_identity("email:alice@gmail.com", v) == "alice"
    assert vault.find_by_identity("email:other@gmail.com", v) is None


def test_store_roundtrip(sandbox, blob_alice):
    store = get_store()
    assert store.get() is None
    store.set(blob_alice)
    assert store.get() == blob_alice
    store.delete()
    assert store.get() is None
