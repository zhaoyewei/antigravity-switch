"""额度探测与 auto 选号的单元测试。

全部离线：`_post` / `access_token` 被替换掉，绝不真实联网。
"""
import json
import os
import time

import pytest

from agys import quota
from agys.cli import main
from agys.config import paths


def _report(acc_id, state="unknown", remaining=None, detail="", models=None):
    return {"id": acc_id, "state": state, "remaining": remaining, "detail": detail,
            "models": models or [], "checked": int(time.time())}


@pytest.fixture
def net(monkeypatch):
    """把网络层替换成可编程的假实现。"""
    monkeypatch.setattr(quota, "access_token",
                        lambda acc_id, cache=None, force=False: "TOKEN")

    class Net:
        def __init__(self):
            self.routes = {}
            self.calls = []

        def route(self, method, status, payload):
            self.routes[method] = (status, payload)

        def __call__(self, method, token, body=None, timeout=20):
            self.calls.append(method)
            return self.routes.get(method, (200, {}))

    n = Net()
    monkeypatch.setattr(quota, "_post", n)
    return n


# ---------------------------------------------------------------- 解析与判定

def test_parse_buckets_finds_fraction_anywhere():
    payload = {"groups": [{"buckets": [
        {"modelId": "gemini-2.5-pro", "remainingFraction": 0.42,
         "resetTime": "2026-12-01T00:00:00Z"}]}]}
    got = quota._parse_buckets(payload)
    assert len(got) == 1
    assert got[0]["model"] == "gemini-2.5-pro"
    assert got[0]["fraction"] == 0.42


def test_probe_ok_reports_remaining(net):
    net.route("retrieveUserQuota", 200, {"buckets": [
        {"modelId": "gemini-2.5-pro", "remainingFraction": 0.8},
        {"modelId": "gemini-2.5-flash", "remainingFraction": 0.6}]})
    r = quota.probe("alice")
    assert r["state"] == "ok" and r["remaining"] == 0.6


def test_probe_zero_fraction_is_exhausted(net):
    net.route("retrieveUserQuota", 200, {"buckets": [
        {"modelId": "gemini-2.5-pro", "remainingFraction": 0.0}]})
    assert quota.probe("alice")["state"] == "exhausted"


def test_probe_403_falls_back_to_health(net):
    net.route("retrieveUserQuota", 403,
              {"error": {"status": "SUBSCRIPTION_REQUIRED"}})
    net.route("countTokens", 200, {"totalTokens": 3})
    r = quota.probe("alice")
    assert r["state"] == "unknown" and "健康探针通过" in r["detail"]
    assert "countTokens" in net.calls


def test_probe_403_with_exhausted_health(net):
    net.route("retrieveUserQuota", 403, {"error": {"status": "SUBSCRIPTION_REQUIRED"}})
    net.route("countTokens", 429, {"error": {"status": "RESOURCE_EXHAUSTED"}})
    assert quota.probe("alice")["state"] == "exhausted"


def test_probe_429_is_exhausted(net):
    net.route("retrieveUserQuota", 429, {"error": {"status": "RESOURCE_EXHAUSTED"}})
    assert quota.probe("alice")["state"] == "exhausted"


def test_probe_401_needs_reauth(net):
    net.route("retrieveUserQuota", 401, {"error": {"status": "UNAUTHENTICATED"}})
    assert quota.probe("alice")["state"] == "auth"


def test_probe_network_failure_is_error(net):
    net.route("retrieveUserQuota", -1, {"error": {"message": "timed out"}})
    assert quota.probe("alice")["state"] == "error"


def test_probe_without_token_is_auth(monkeypatch):
    def boom(acc_id, cache=None, force=False):
        raise RuntimeError("没有可用的 refresh_token")
    monkeypatch.setattr(quota, "access_token", boom)
    r = quota.probe("ghost")
    assert r["state"] == "auth" and "refresh_token" in r["detail"]


# ---------------------------------------------------------------- 排序与缓存

def test_rank_orders_by_state_then_remaining():
    rows = [
        _report("c", "exhausted"),
        _report("b", "ok", remaining=0.2),
        _report("a", "ok", remaining=0.9),
        _report("d", "auth"),
    ]
    assert [r["id"] for r in quota.rank(rows)] == ["a", "b", "c", "d"]
    assert quota.usable(rows[1]) and not quota.usable(rows[0])


def test_rank_prefers_longest_idle_within_same_state():
    rows = [_report("new", "unknown"), _report("old", "unknown")]
    for r in rows:
        r["last_switch"] = {"new": "2026-11-26", "old": "2026-10-01"}[r["id"]]
    assert [r["id"] for r in quota.rank(rows)] == ["old", "new"]


def test_snapshot_offline_never_probes(sandbox, net, monkeypatch):
    import agys.vault as vault_mod
    v = {"accounts": {"alice": {"email": "alice@gmail.com"},
                      "bob": {"email": "bob@gmail.com"}}}
    quota.save_cache({"accounts": {
        "alice": {"state": "ok", "checked": int(time.time()), "remaining": 0.5},
        "bob": {"state": "exhausted", "checked": int(time.time()), "remaining": 0.0},
    }})
    rows = quota.snapshot(v, offline=True)
    assert net.calls == []
    assert rows[0]["id"] == "alice" and rows[0]["remaining"] == 0.5
    assert rows[1]["state"] == "exhausted"
    assert rows[0]["email"] == "alice@gmail.com"


def test_snapshot_without_cache_marks_unknown(sandbox, net):
    v = {"accounts": {"alice": {"email": "alice@gmail.com"}}}
    net.route("retrieveUserQuota", 403, {"error": {"status": "SUBSCRIPTION_REQUIRED"}})
    rows = quota.snapshot(v)
    assert rows[0]["state"] == "unknown"
    cache_file = os.path.join(paths().home, "quota.json")
    assert json.loads(open(cache_file, encoding="utf-8").read())["accounts"]


def test_mark_persists_exhausted(sandbox):
    quota.mark("alice", "exhausted", "agy 3s 后退出")
    entry = quota.load_cache()["accounts"]["alice"]
    assert entry["state"] == "exhausted" and entry["remaining"] == 0.0


def test_describe_labels():
    assert "额度已用尽" in quota.describe(_report("a", "exhausted"))
    assert "40%" in quota.describe(_report("a", "ok", remaining=0.4))
    assert "（无配额包）" in quota.describe(_report("a", "unknown", detail="无配额包"))


# ---------------------------------------------------------------- 命令层

def test_bare_agys_without_accounts_exits_1(sandbox, capsys):
    assert main([]) == 1
    assert "还没有任何帐号" in capsys.readouterr().err


def _two_accounts(monkeypatch, blob_alice, blob_bob):
    for blob, email, name in ((blob_alice, "alice@gmail.com", "alice"),
                              (blob_bob, "bob@gmail.com", "bob")):
        monkeypatch.setenv("AGYS_STUB_BLOB", blob.decode("utf-8"))
        monkeypatch.setenv("AGYS_STUB_EMAIL", email)
        assert main(["add", name]) == 0


def test_auto_dry_run_chooses_highest_remaining(sandbox, monkeypatch, capsys,
                                                blob_alice, blob_bob):
    _two_accounts(monkeypatch, blob_alice, blob_bob)
    monkeypatch.setattr(quota, "probe", lambda acc_id, cache=None: _report(
        acc_id, "ok" if acc_id == "bob" else "exhausted",
        remaining=0.7 if acc_id == "bob" else 0.0))
    capsys.readouterr()
    assert main(["--json", "auto", "--dry-run"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["choice"] == "bob"


def test_auto_switches_and_skips_exhausted(sandbox, monkeypatch, capsys,
                                           blob_alice, blob_bob):
    _two_accounts(monkeypatch, blob_alice, blob_bob)
    monkeypatch.setattr(quota, "probe", lambda acc_id, cache=None: _report(
        acc_id, "ok" if acc_id == "alice" else "exhausted",
        remaining=0.5 if acc_id == "alice" else 0.0))
    capsys.readouterr()
    assert main(["auto", "--no-launch"]) == 0
    captured = capsys.readouterr()
    assert "跳过帐号 'bob'" in captured.err       # 警告统一走 stderr
    assert "已切到 'alice'" in captured.out


def test_auto_all_exhausted_errors(sandbox, monkeypatch, capsys,
                                   blob_alice, blob_bob):
    _two_accounts(monkeypatch, blob_alice, blob_bob)
    monkeypatch.setattr(quota, "probe",
                        lambda acc_id, cache=None: _report(acc_id, "exhausted", 0.0))
    capsys.readouterr()
    assert main(["auto", "--no-launch"]) == 1
    assert "没有可用帐号" in capsys.readouterr().err


def test_auto_status_lists_all_accounts(sandbox, monkeypatch, capsys,
                                        blob_alice, blob_bob):
    _two_accounts(monkeypatch, blob_alice, blob_bob)
    monkeypatch.setattr(quota, "probe", lambda acc_id, cache=None: _report(
        acc_id, "unknown", detail="无配额包（免费帐号），健康探针通过"))
    capsys.readouterr()
    assert main(["auto", "--status"]) == 0
    text = capsys.readouterr().out
    assert "alice" in text and "bob" in text and "额度未知" in text


# ---------------------------------------------------------------- 启动即失败 → 自动换号

def _fallback_args():
    import argparse
    return argparse.Namespace(no_guard=False, close_all=False, yes=False,
                              allow_layout_change=False)


def test_fallback_switches_after_confirmed_exhaustion(sandbox, monkeypatch, capsys):
    from agys.commands import switching
    from agys.common import Reporter

    seen, launched = [], []
    monkeypatch.setattr(switching, "switch_if_needed", lambda acc, *a: seen.append(acc))
    monkeypatch.setattr(switching, "launch",
                        lambda tail, rep: (launched.append(1), 1)[1])
    monkeypatch.setattr(switching.quota, "probe", lambda acc_id, cache=None: _report(
        acc_id, "exhausted", 0.0, detail="429 配额耗尽"))
    monkeypatch.setattr(switching.quota, "mark",
                        lambda acc_id, state, detail: seen.append(("mark", acc_id)))

    rep = Reporter(False)
    rc = switching._run_with_fallback(["a", "b"], _fallback_args(), rep, None,
                                      {"current": None}, [])
    assert rc == 1
    assert len(launched) == 2, "两个帐号都应被尝试"
    # 首个帐号已由 cmd_auto 切好，循环里不该重复切换，只切第二个
    assert seen == [("mark", "a"), "b", ("mark", "b")]
    assert "额度已用尽" in capsys.readouterr().err


def test_fallback_keeps_account_when_not_quota(sandbox, monkeypatch, capsys):
    from agys.commands import switching
    from agys.common import Reporter

    seen, launched = [], []
    monkeypatch.setattr(switching, "switch_if_needed", lambda acc, *a: seen.append(acc))
    monkeypatch.setattr(switching, "launch",
                        lambda tail, rep: (launched.append(1), 3)[1])
    monkeypatch.setattr(switching.quota, "probe",
                        lambda acc_id, cache=None: _report(acc_id, "error"))
    monkeypatch.setattr(switching.quota, "mark",
                        lambda *a: seen.append("MARK-SHOULD-NOT-HAPPEN"))

    rc = switching._run_with_fallback(["a", "b"], _fallback_args(), Reporter(False),
                                      None, {"current": None}, [])
    assert rc == 3 and len(launched) == 1 and seen == [], "非额度问题不应换号"


def test_fallback_ignores_user_cancel(sandbox, monkeypatch):
    from agys.commands import switching
    from agys.common import Reporter

    launched = []
    monkeypatch.setattr(switching, "switch_if_needed",
                        lambda acc, *a: pytest.fail("取消不该换号"))
    monkeypatch.setattr(switching, "launch",
                        lambda tail, rep: (launched.append(1), 130)[1])
    monkeypatch.setattr(switching.quota, "probe",
                        lambda acc_id, cache=None: _report(acc_id, "exhausted", 0.0))
    rc = switching._run_with_fallback(["a", "b"], _fallback_args(), Reporter(False),
                                      None, {"current": None}, [])
    assert rc == 130 and len(launched) == 1, "用户取消不该被当成额度耗尽"


def test_fallback_respects_window(sandbox, monkeypatch):
    from agys.commands import switching
    from agys.common import Reporter

    launched = []
    monkeypatch.setenv("AGYS_AUTO_FASTFAIL", "0")
    monkeypatch.setattr(switching, "switch_if_needed",
                        lambda acc, *a: pytest.fail("超出窗口不该换号"))
    monkeypatch.setattr(switching, "launch",
                        lambda tail, rep: (launched.append(1), 1)[1])
    rc = switching._run_with_fallback(["a", "b"], _fallback_args(), Reporter(False),
                                      None, {"current": None}, [])
    assert rc == 1 and len(launched) == 1, "超过判定窗口的失败不换号"


def test_window_env_parsing(sandbox, monkeypatch):
    from agys.commands import switching
    assert switching._fallback_window() == 20.0
    monkeypatch.setenv("AGYS_AUTO_FASTFAIL", "45")
    assert switching._fallback_window() == 45.0
    monkeypatch.setenv("AGYS_AUTO_FASTFAIL", "not-a-number")
    assert switching._fallback_window() == 20.0


def test_auto_offline_env_is_honoured(sandbox, monkeypatch, capsys, blob_alice):
    from agys.commands import switching
    monkeypatch.setenv("AGYS_AUTO_OFFLINE", "1")
    monkeypatch.setenv("AGYS_STUB_BLOB", blob_alice.decode("utf-8"))
    monkeypatch.setenv("AGYS_STUB_EMAIL", "alice@gmail.com")
    assert main(["add", "alice"]) == 0
    monkeypatch.setattr(switching.quota, "_post",
                        lambda *a, **k: pytest.fail("离线模式不应联网"))
    capsys.readouterr()
    assert main(["auto", "--status"]) == 0
    assert "未探测" in capsys.readouterr().out


def test_auto_falls_back_to_trying_when_probe_fails(sandbox, monkeypatch, capsys,
                                                    blob_alice):
    """所有帐号都「探测失败」时不该把用户挡在门外，而是按顺序试。"""
    monkeypatch.setenv("AGYS_STUB_BLOB", blob_alice.decode("utf-8"))
    monkeypatch.setenv("AGYS_STUB_EMAIL", "alice@gmail.com")
    assert main(["add", "alice"]) == 0
    monkeypatch.setattr(quota, "probe",
                        lambda acc_id, cache=None: _report(acc_id, "error",
                                                           detail="配额接口返回 -1"))
    capsys.readouterr()
    assert main(["auto", "--no-launch"]) == 0
    captured = capsys.readouterr()
    assert "网络或代理" in captured.err
    assert "已切到 'alice'" in captured.out


def test_pad_counts_wide_chars():
    """中文按 2 列算，否则状态表会歪。"""
    from agys.common import disp_width, pad
    assert disp_width("可用") == 4
    assert disp_width("ok") == 2
    assert pad("可用", 8) == "可用    "
    assert pad("ok", 4) == "ok  "
    assert pad("超出宽度", 2) == "超出宽度"      # 只补不砍


# ---------------------------------------------------------------- 重置时间

def test_reset_epoch_variants():
    import datetime
    iso = quota.reset_epoch("2026-12-01T00:00:00Z")
    assert abs(iso - datetime.datetime(
        2026, 12, 1, tzinfo=datetime.timezone.utc).timestamp()) < 1
    assert quota.reset_epoch("1799000000") == 1799000000.0
    assert quota.reset_epoch("1799000000000") == 1799000000.0
    assert quota.reset_epoch("") is None
    assert quota.reset_epoch("not-a-date") is None


def test_fmt_reset_localizes():
    import datetime
    expected = datetime.datetime(2026, 12, 1, tzinfo=datetime.timezone.utc
                                  ).astimezone().strftime("%m-%d %H:%M")
    assert quota.fmt_reset("2026-12-01T00:00:00Z") == expected
    assert quota.fmt_reset("garbage") == "garbage"
    assert quota.fmt_reset("") == ""


def test_probe_captures_reset_time(net):
    net.route("retrieveUserQuota", 200, {"buckets": [
        {"modelId": "gemini-2.5-pro", "remainingFraction": 0.0,
         "resetTime": "2026-12-01T00:00:00Z"}]})
    r = quota.probe("alice")
    assert r["state"] == "exhausted"
    assert r["reset"] == "2026-12-01T00:00:00Z"
    assert "重置" in quota.label(r)
    assert "12-01" in quota.label(r)


def test_label_without_reset_keeps_plain():
    assert "重置" not in quota.label(_report("a", "exhausted"))
    assert "重置" not in quota.label(_report("a", "ok", remaining=0.5))


def test_snapshot_caches_reset(sandbox, net):
    v = {"accounts": {"alice": {"email": "a@gmail.com"}}}
    net.route("retrieveUserQuota", 200, {"buckets": [
        {"modelId": "m", "remainingFraction": 0.0,
         "resetTime": "2026-12-01T00:00:00Z"}]})
    rows = quota.snapshot(v, offline=False)
    assert rows[0]["reset"] == "2026-12-01T00:00:00Z"
    cached = quota.load_cache()["accounts"]["alice"]
    assert cached["reset"] == "2026-12-01T00:00:00Z"
    # 离线读缓存也应带出 reset
    rows2 = quota.snapshot(v, offline=True)
    assert rows2[0]["reset"] == "2026-12-01T00:00:00Z"


# ---------------------------------------------------------------- 会话中途 429 兜底

class _FakeTime:
    """每次 monotonic() 前进一段，模拟长会话的运行耗时。"""

    def __init__(self, step=300.0):
        self.t = 1000.0
        self.step = step

    def monotonic(self):
        self.t += self.step
        return self.t


def test_fallback_mid_session_exhausted_switches(sandbox, monkeypatch, capsys):
    """长会话中额度耗尽：只要 agy 已退出就兜底换号（绝不中途打断）。"""
    from agys.commands import switching
    from agys.common import Reporter

    switched, marks = [], []
    monkeypatch.setattr(switching, "time", _FakeTime(300.0))
    monkeypatch.setattr(switching, "switch_if_needed",
                        lambda acc, *a: switched.append(acc))
    monkeypatch.setattr(switching, "launch", lambda tail, rep: 1)
    monkeypatch.setattr(switching.quota, "probe", lambda acc_id, cache=None: _report(
        acc_id, "exhausted", 0.0, detail="429 配额耗尽"))
    monkeypatch.setattr(switching.quota, "mark",
                        lambda acc, state, detail: marks.append(acc))

    rc = switching._run_with_fallback(["a", "b"], _fallback_args(), Reporter(False),
                                      None, {"current": None}, [])
    assert rc == 1
    assert switched == ["b"], "长会话撞 429 也应换号"
    assert marks == ["a", "b"]
    err = capsys.readouterr().err
    assert "300 秒后退出" in err and "额度已用尽" in err


def test_fallback_mid_session_not_quota_only_hints(sandbox, monkeypatch, capsys):
    """长会话失败但不是额度问题：不换号，只提示查看真实输出。"""
    from agys.commands import switching
    from agys.common import Reporter

    monkeypatch.setattr(switching, "time", _FakeTime(300.0))
    monkeypatch.setattr(switching, "switch_if_needed",
                        lambda acc, *a: pytest.fail("非额度问题不该换号"))
    monkeypatch.setattr(switching, "launch", lambda tail, rep: 3)
    monkeypatch.setattr(switching.quota, "probe",
                        lambda acc_id, cache=None: _report(acc_id, "error"))

    rc = switching._run_with_fallback(["a", "b"], _fallback_args(), Reporter(False),
                                      None, {"current": None}, [])
    assert rc == 3
    err = capsys.readouterr().err
    assert "不是额度问题" in err


def test_as_post_launch_check_warns(sandbox, monkeypatch, capsys):
    from agys.commands import switching
    from agys.common import Reporter

    monkeypatch.setattr(switching, "_probe_after_failure",
                        lambda acc, rep: _report(acc, "exhausted", 0.0))
    monkeypatch.setattr(switching.quota, "mark", lambda *a: None)
    switching._post_launch_check("alice", Reporter(False))
    err = capsys.readouterr().err
    assert "额度已用尽" in err and "运行 agys" in err
