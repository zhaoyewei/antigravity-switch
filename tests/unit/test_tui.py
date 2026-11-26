import pytest

from agys import tui


def _accounts():
    return {
        "alice": {"id": "alice", "email": "alice@gmail.com",
                  "aliases": ["a", "primary"], "identity": "email:alice@gmail.com"},
        "bob": {"id": "bob", "email": "bob@gmail.com",
                "aliases": [], "identity": "email:bob@gmail.com"},
    }


class _StubKeys:
    def __init__(self, seq):
        self.seq = list(seq)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self.seq.pop(0) if self.seq else "quit"


def test_render_marks_current_and_selection():
    rows = tui._rows([{"id": "alice", "email": "alice@gmail.com",
                       "aliases": ["a"], "identity": "email:alice@gmail.com"},
                      {"id": "bob", "email": "bob@gmail.com",
                       "aliases": [], "identity": "email:bob@gmail.com"}], "alice")
    lines = tui.render(rows, 0, "alice", "email:alice@gmail.com")
    text = "\n".join(lines)
    assert "当前帐号   alice" in text
    assert "活跃凭据 email:alice@gmail.com" in text
    assert "▸" in text
    assert "a" in text
    assert "未纳入管理" not in text


def test_render_warns_on_unmanaged_active_credential():
    rows = tui._rows([{"id": "alice", "email": "alice@gmail.com",
                       "aliases": [], "identity": "email:alice@gmail.com"}], None)
    text = "\n".join(tui.render(rows, 0, None, "email:someone@gmail.com"))
    assert "当前帐号   无" in text
    assert "未纳入管理" in text


def test_render_marks_unmanaged_account():
    rows = tui._rows([{"id": "carol", "email": "c@x.com", "aliases": [],
                       "identity": "email:c@x.com"}], None)
    text = "\n".join(tui.render(rows, 0, None, None))
    assert "当前帐号   无" in text
    assert "活跃凭据 无" in text


def test_fit_truncates_wide_chars():
    assert tui._fit("abcdef", 3) == "abc"
    assert tui._fit("中文中文", 4) == "中文"
    assert tui._fit("abc", 0) == ""


def test_pick_requires_tty(monkeypatch):
    monkeypatch.setattr(tui, "supported", lambda: False)
    with pytest.raises(RuntimeError):
        tui.pick(_accounts())


def test_pick_empty_accounts():
    assert tui.pick({}) is None


def test_pick_down_then_enter(monkeypatch):
    monkeypatch.setattr(tui, "supported", lambda: True)
    monkeypatch.setattr(tui, "_Keys", lambda: _StubKeys(["down", "enter"]))
    assert tui.pick(_accounts(), current="alice") == "bob"


def test_pick_wraps_around(monkeypatch):
    monkeypatch.setattr(tui, "supported", lambda: True)
    monkeypatch.setattr(tui, "_Keys", lambda: _StubKeys(["up", "enter"]))
    assert tui.pick(_accounts(), current="alice") == "bob"


def test_pick_digit_jump(monkeypatch):
    monkeypatch.setattr(tui, "supported", lambda: True)
    monkeypatch.setattr(tui, "_Keys", lambda: _StubKeys(["2", "enter"]))
    assert tui.pick(_accounts(), current="alice") == "bob"


def test_pick_quit_returns_none(monkeypatch):
    monkeypatch.setattr(tui, "supported", lambda: True)
    monkeypatch.setattr(tui, "_Keys", lambda: _StubKeys(["q"]))
    assert tui.pick(_accounts(), current="alice") is None


def test_cli_tui_without_accounts(sandbox, capsys):
    from agys.cli import main
    capsys.readouterr()
    assert main(["tui"]) == 1
    assert "还没有任何帐号" in capsys.readouterr().err


def test_cli_use_without_name_non_tty(sandbox, monkeypatch, capsys, blob_alice):
    from agys.cli import main
    monkeypatch.setenv("AGYS_STUB_BLOB", blob_alice.decode("utf-8"))
    monkeypatch.setenv("AGYS_STUB_EMAIL", "alice@gmail.com")
    assert main(["add"]) == 0
    capsys.readouterr()
    # pytest 下 stdin 不是 TTY，省略帐号应明确报错而不是卡住
    assert main(["use"]) == 1
    assert "用法：agys use" in capsys.readouterr().err
