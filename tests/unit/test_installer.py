"""免 Python 安装链路的纯逻辑单测（不联网、不碰真实安装目录）。"""
import json
import os

import pytest

from agys import installer
from agys.cli import main


# ---------------------------------------------------------------- 产物命名

@pytest.mark.parametrize("system,machine,expected", [
    ("win32", "AMD64", "agys-windows-x86_64.exe"),
    ("MINGW64_NT-10.0", "x86_64", "agys-windows-x86_64.exe"),
    ("Windows-11", "ARM64", "agys-windows-arm64.exe"),
    ("linux", "x86_64", "agys-linux-x86_64"),
    ("Linux", "aarch64", "agys-linux-arm64"),
    ("Darwin", "arm64", "agys-macos-arm64"),
    ("darwin", "x86_64", "agys-macos-x86_64"),
    ("freebsd", "x86_64", ""),
    ("linux", "mips", ""),
])
def test_asset_name(system, machine, expected):
    assert installer.asset_name(system=system, machine=machine) == expected


def test_asset_name_matches_current_platform():
    assert installer.asset_name() != ""   # CI 覆盖的三平台都能产出名字


# ---------------------------------------------------------------- URL

def test_release_asset_url_latest(monkeypatch):
    monkeypatch.delenv("GITHUB_OWNER", raising=False)
    monkeypatch.delenv("AGYS_GITHUB_OWNER", raising=False)
    assert installer.release_asset_url("agys-linux-x86_64") == (
        "https://github.com/zhaoyewei/antigravity-switch/releases/"
        "latest/download/agys-linux-x86_64")


def test_release_asset_url_pinned_tag(monkeypatch):
    monkeypatch.setenv("GITHUB_OWNER", "someone")
    assert installer.release_asset_url("agys-windows-x86_64.exe", ref="v0.7.0") == (
        "https://github.com/someone/antigravity-switch/releases/"
        "download/v0.7.0/agys-windows-x86_64.exe")
    assert installer.release_asset_url("") == ""


def test_installer_url(monkeypatch):
    monkeypatch.delenv("GITHUB_OWNER", raising=False)
    monkeypatch.delenv("AGYS_GITHUB_OWNER", raising=False)
    monkeypatch.delenv("AGYS_REF", raising=False)
    assert installer.installer_url("install.sh") == (
        "https://raw.githubusercontent.com/zhaoyewei/antigravity-switch/"
        "main/install.sh")
    monkeypatch.setenv("AGYS_REF", "v0.7.0")
    assert installer.installer_url("install.ps1").endswith(
        "/v0.7.0/install.ps1")


# ---------------------------------------------------------------- 安装模式标记

def test_mode_marker_roundtrip(sandbox, monkeypatch):
    dest = str(sandbox["home"] / "agys-install")
    monkeypatch.setenv("AGYS_INSTALL_DIR", dest)
    assert installer.read_mode() == ""
    assert installer.write_mode("binary").endswith("install-mode")
    assert installer.read_mode() == "binary"
    installer.write_mode("SOURCE")
    assert installer.read_mode() == "source"


def test_update_script_choice():
    assert installer.update_script("binary", system="win32") == "install.ps1"
    assert installer.update_script("binary", system="linux") == "install.sh"
    assert installer.update_script("source", system="win32") == "install.sh"
    assert installer.update_script("", system="win32") == "install.sh"


# ---------------------------------------------------------------- agys update 分派

def _json(main_args, capsys):
    capsys.readouterr()
    rc = main(main_args)
    out = capsys.readouterr().out
    return rc, json.loads(out)


def test_update_uses_powershell_for_binary_windows(sandbox, monkeypatch, capsys):
    from agys.commands import diag

    monkeypatch.setenv("AGYS_INSTALL_DIR", str(sandbox["home"] / "agys-install"))
    installer.write_mode("binary")
    monkeypatch.setattr(installer, "update_script", lambda mode, system=None: "install.ps1")

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"Write-Host 'installer'"

    monkeypatch.setattr(diag.proxy, "urlopen", lambda url, timeout=30: Resp())
    seen = {}
    monkeypatch.setattr(diag.subprocess, "call",
                        lambda cmd, env=None: (seen.setdefault("cmd", cmd), 0)[1])

    rc, out = _json(["--json", "update"], capsys)
    assert rc == 0 and out["updated"] is True
    assert out["mode"] == "binary" and out["installer"] == "install.ps1"
    assert seen["cmd"][0] == "powershell" and seen["cmd"][-1].endswith(".ps1")


def test_update_uses_bash_for_source_install(sandbox, monkeypatch, capsys):
    from agys.commands import diag

    monkeypatch.setenv("AGYS_INSTALL_DIR", str(sandbox["home"] / "agys-install"))
    installer.write_mode("source")

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"#!/bin/sh\necho installer\n"

    monkeypatch.setattr(diag.proxy, "urlopen", lambda url, timeout=30: Resp())
    seen = {}
    monkeypatch.setattr(diag.subprocess, "call",
                        lambda cmd, env=None: (seen.setdefault("cmd", cmd), 0)[1])

    rc, out = _json(["--json", "update"], capsys)
    assert rc == 0 and out["installer"] == "install.sh"
    assert seen["cmd"][0] == "bash" and seen["cmd"][-1].endswith(".sh")


def test_update_check_still_reports_versions(sandbox, monkeypatch, capsys):
    from agys.commands import diag
    from agys import __version__
    monkeypatch.setattr(diag, "_latest_version", lambda: "9.9.9")
    rc, out = _json(["--json", "update", "--check"], capsys)
    assert rc == 0 and out["current"] == __version__ and out["latest"] == "9.9.9"
