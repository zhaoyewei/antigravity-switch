from agys import layout, vault
from agys.credentials import get_store


def test_fingerprint_stable(sandbox):
    store = get_store()
    assert layout.probe(store)["fingerprint"] == layout.probe(store)["fingerprint"]


def test_fingerprint_changes_with_target(sandbox, monkeypatch):
    store = get_store()
    a = layout.probe(store)["fingerprint"]
    monkeypatch.setenv("AGYS_CRED_TARGET", "gemini:other")
    assert layout.probe(store)["fingerprint"] != a


def test_verify_records_then_refuses_change(sandbox, monkeypatch):
    store = get_store()
    v = vault.load_vault()
    ok, msg = layout.verify(v, store)
    assert ok and "记录" in msg
    monkeypatch.setenv("AGYS_CRED_TARGET", "gemini:other")
    ok, msg = layout.verify(v, store)
    assert not ok and "拒绝" in msg
    assert layout.verify(v, store, allow_change=True)[0] is True
