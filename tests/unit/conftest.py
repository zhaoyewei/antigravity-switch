import os
import sys
from pathlib import Path

import pytest

STUB = str(Path(__file__).resolve().parents[1] / "integration" / "login_stub.py")


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    home = tmp_path / "agy"
    gemini = tmp_path / "gemini"
    home.mkdir()
    gemini.mkdir()
    monkeypatch.setenv("AGYS_HOME", str(home))
    monkeypatch.setenv("AGYS_GEMINI_HOME", str(gemini))
    monkeypatch.setenv("AGYS_BACKEND", "memory")
    monkeypatch.setenv("AGYS_MEMORY_FILE", str(home / "memory_credential.json"))
    monkeypatch.setenv("AGYS_PROCESS_NAMES", "")
    monkeypatch.setenv("AGYS_AGY_BIN", f'"{sys.executable}" {STUB}')
    monkeypatch.setenv("AGYS_STUB_GEMINI_HOME", str(gemini))
    monkeypatch.setenv("AGYS_STUB_MEMORY_FILE", str(home / "memory_credential.json"))
    monkeypatch.delenv("AGYS_STUB_BLOB", raising=False)
    monkeypatch.delenv("AGYS_STUB_EMAIL", raising=False)
    monkeypatch.delenv("AGYS_NO_ENCRYPT", raising=False)
    return {"home": home, "gemini": gemini}


@pytest.fixture
def blob_alice():
    return b'{"auth_method":"oauth","token":{"refresh_token":"ALICE-RT-1","email":"alice@gmail.com"}}'


@pytest.fixture
def blob_bob():
    return b'{"auth_method":"oauth","token":{"refresh_token":"BOB-RT-1","email":"bob@gmail.com"}}'
