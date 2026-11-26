from agys import layout, vault
from agys.config import get_overrides, paths
from agys.credentials import get_store


def test_fingerprint_stable(sandbox):
    store = get_store()
    assert layout.probe(store)["fingerprint"] == layout.probe(store)["fingerprint"]


def test_fingerprint_changes_with_target(sandbox, monkeypatch):
    store = get_store()
    a = layout.probe(store)["fingerprint"]
    monkeypatch.setenv("AGYS_CRED_TARGET", "gemini:other")
    assert layout.probe(store)["fingerprint"] != a


def test_fingerprint_ignores_agy_version(sandbox, monkeypatch):
    """agy 升级只改版本号，不该被当成「存储布局变化」。"""
    store = get_store()
    monkeypatch.setattr(layout, "agy_version", lambda: "agy 1.0.0")
    a = layout.probe(store)["fingerprint"]
    monkeypatch.setattr(layout, "agy_version", lambda: "agy 9.9.9")
    b = layout.probe(store)
    assert b["fingerprint"] == a
    assert b["agy_version"] == "agy 9.9.9"


def test_verify_records_first_time(sandbox):
    store = get_store()
    v = vault.load_vault()
    ok, msg = layout.verify(v, store)
    assert ok and "记录" in msg
    assert v["layout"]["structure"]["cred_target"] == "gemini:antigravity"


def test_version_bump_does_not_block(sandbox, monkeypatch):
    store = get_store()
    v = vault.load_vault()
    monkeypatch.setattr(layout, "agy_version", lambda: "agy 1.0.0")
    assert layout.verify(v, store)[0] is True
    monkeypatch.setattr(layout, "agy_version", lambda: "agy 2.0.0")
    ok, msg = layout.verify(v, store)
    assert ok and "存储结构未变" in msg and "agy 2.0.0" in msg


def test_env_pinned_change_is_accepted(sandbox, monkeypatch):
    """用户显式改了环境变量 —— 这是配置，不是 agy 偷换位置，直接采纳。"""
    store = get_store()
    v = vault.load_vault()
    layout.verify(v, store)
    monkeypatch.setenv("AGYS_CRED_TARGET", "gemini:other")
    ok, msg = layout.verify(v, store)
    assert ok and "环境变量" in msg
    assert v["layout"]["structure"]["cred_target"] == "gemini:other"


def test_verify_refuses_when_nothing_alive(sandbox):
    store = get_store()
    v = vault.load_vault()
    layout.verify(v, store)
    # 缓存指向一个根本不存在的位置，当前也没有任何活跃凭据或状态文件
    v["layout"]["structure"]["cred_target"] = "gemini:gone"
    v["layout"]["structure"]["ga_path"] = str(sandbox["gemini"] / "nope.json")
    v["layout"]["fingerprint"] = "0000000000000000"
    vault.save_vault(v)
    ok, msg = layout.verify(v, store)
    assert not ok and "拒绝" in msg
    assert layout.verify(v, store, allow_change=True)[0] is True


def test_discover_includes_default_layout(sandbox):
    store = get_store()
    cands = layout.discover(store)
    assert cands
    assert cands[0]["fingerprint"] == layout.probe(store)["fingerprint"]
    assert cands[0]["overrides"] == {}


def test_apply_cached_prunes_stale_override(sandbox):
    v = vault.load_vault()
    missing = str(sandbox["gemini"] / "moved" / "google_accounts.json")
    v["layout"] = {"overrides": {"ga": missing}}
    assert layout.apply_cached(v) is False
    assert get_overrides() == {}
    assert paths().ga != missing


def test_apply_cached_keeps_live_override(sandbox):
    v = vault.load_vault()
    live = str(sandbox["gemini"] / "google_accounts.json")
    v["layout"] = {"overrides": {"ga": live}}
    assert layout.apply_cached(v) is True
    assert get_overrides()["ga"] == live
    assert paths().ga == live
    layout.apply_cached({})  # 清理，避免影响其它用例
    assert get_overrides() == {}
