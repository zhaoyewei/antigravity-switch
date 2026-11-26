"""代理配置单元测试。"""
import json
import os

import pytest

from agys import proxy
from agys.cli import main
from agys.common import AgysError


def _no_env(monkeypatch):
    monkeypatch.delenv("AGYS_PROXY", raising=False)
    monkeypatch.delenv("AGYS_NO_PROXY", raising=False)
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)


def test_normalize():
    assert proxy.normalize("127.0.0.1:7890") == "http://127.0.0.1:7890"
    assert proxy.normalize("socks5://127.0.0.1:7890") == "socks5://127.0.0.1:7890"
    assert proxy.normalize("") == ""
    assert proxy.normalize("  http://u:p@127.0.0.1:7890 ") == "http://u:p@127.0.0.1:7890"
    with pytest.raises(AgysError):
        proxy.normalize("ftp://127.0.0.1:21")
    with pytest.raises(AgysError):
        proxy.normalize("http://")
    with pytest.raises(AgysError):
        proxy.normalize("http://127.0.0.1:notaport")


def test_mask():
    assert proxy.mask("http://127.0.0.1:7890") == "http://127.0.0.1:7890"
    assert proxy.mask("http://u:secret@127.0.0.1:7890") == "http://u:***@127.0.0.1:7890"
    assert proxy.mask("") == ""


def test_save_load_clear(sandbox, monkeypatch):
    _no_env(monkeypatch)
    assert proxy.current() is None

    url = proxy.set_proxy("127.0.0.1:7890")
    assert url == "http://127.0.0.1:7890"
    assert proxy.current() == url
    cfg_path = os.path.join(str(sandbox["home"]), "config.json")
    assert os.path.isfile(cfg_path)
    with open(cfg_path, encoding="utf-8") as f:
        assert json.load(f)["proxy"] == url

    proxy.clear_proxy()
    assert proxy.current() is None


def test_child_env_injects(sandbox, monkeypatch):
    _no_env(monkeypatch)
    proxy.set_proxy("http://127.0.0.1:7890")
    env = proxy.child_env({"PATH": "/bin", "NO_PROXY": "example.com"})
    assert env["HTTP_PROXY"] == "http://127.0.0.1:7890"
    assert env["http_proxy"] == "http://127.0.0.1:7890"
    assert env["https_proxy"] == "http://127.0.0.1:7890"
    assert env["ALL_PROXY"] == "http://127.0.0.1:7890"
    assert "example.com" in env["NO_PROXY"]
    assert "127.0.0.1" in env["NO_PROXY"]
    assert env["PATH"] == "/bin"


def test_child_env_noop_without_proxy(sandbox, monkeypatch):
    _no_env(monkeypatch)
    env = proxy.child_env({"PATH": "/bin"})
    assert "HTTP_PROXY" not in env
    assert env["PATH"] == "/bin"


def test_env_override_and_disable(sandbox, monkeypatch):
    _no_env(monkeypatch)
    proxy.set_proxy("http://127.0.0.1:1111")
    monkeypatch.setenv("AGYS_PROXY", "socks5://127.0.0.1:2222")
    assert proxy.current() == "socks5://127.0.0.1:2222"
    monkeypatch.setenv("AGYS_NO_PROXY", "1")
    assert proxy.current() is None


def test_show_set_clear_cli(sandbox, monkeypatch, capsys):
    _no_env(monkeypatch)
    capsys.readouterr()
    assert main(["proxy"]) == 0
    assert "未配置代理" in capsys.readouterr().out

    # 端口 1 必然连不上：配置应保存成功，但连通性检测给警告
    assert main(["proxy", "set", "127.0.0.1:1"]) == 0
    cap = capsys.readouterr()
    assert "已设置代理" in cap.out
    assert "连通性检测失败" in cap.err

    assert main(["proxy", "show"]) == 0
    assert "127.0.0.1:1" in capsys.readouterr().out

    assert main(["proxy", "clear"]) == 0
    assert proxy.current() is None
    capsys.readouterr()
    assert main(["proxy"]) == 0
    assert "未配置代理" in capsys.readouterr().out


def test_proxy_json_output(sandbox, monkeypatch, capsys):
    _no_env(monkeypatch)
    capsys.readouterr()
    assert main(["--json", "proxy", "set", "127.0.0.1:1"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is True
    assert data["proxy"] == "http://127.0.0.1:1"
    assert data["reachable"] is False
