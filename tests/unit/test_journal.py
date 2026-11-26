import json

from agys import journal, vault
from agys.credentials import get_store


def test_recover_rolls_back(sandbox, blob_alice, blob_bob):
    store = get_store()
    v = vault.load_vault()
    v["current"] = "alice"
    v["accounts"]["alice"] = {"id": "alice", "email": "a@b.com", "aliases": []}
    vault.save_vault(v)
    journal.begin(target="bob", before_cred=blob_alice,
                  before_ga={"active": "alice@gmail.com", "old": []},
                  before_current="alice", after_cred=blob_bob,
                  after_ga={"active": "bob@gmail.com", "old": []},
                  after_current="bob")
    journal.set_phase("credential")
    store.set(blob_bob)
    v["current"] = "bob"
    vault.save_vault(v)

    msg = journal.recover(store)
    assert msg and "回滚" in msg
    assert store.get() == blob_alice
    assert vault.load_vault()["current"] == "alice"
    assert journal._read() is None


def test_finish_clears(sandbox, blob_alice):
    store = get_store()
    journal.begin(target="x", before_cred=None, before_ga=None,
                  before_current=None, after_cred=blob_alice,
                  after_ga={}, after_current="x")
    journal.finish()
    assert journal.recover(store) is None
