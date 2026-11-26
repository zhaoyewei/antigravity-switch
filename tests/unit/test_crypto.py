import os

import pytest

from agys import crypto
from agys.config import IS_WIN


def test_roundtrip(sandbox):
    data = b'{"token":"secret","n":123}'
    sealed = crypto.seal(data)
    assert sealed != data
    assert crypto.unseal(sealed) == data


def test_two_ciphertexts_differ(sandbox):
    a = crypto.seal(b"same")
    b = crypto.seal(b"same")
    assert crypto.unseal(a) == crypto.unseal(b) == b"same"
    assert a != b  # 随机 nonce / DPAPI salt


def test_plaintext_mode_compatible(sandbox, monkeypatch):
    monkeypatch.setenv("AGYS_NO_ENCRYPT", "1")
    sealed = crypto.seal(b"legacy")
    assert sealed.startswith(crypto.MAGIC_PLAIN)
    assert crypto.unseal(sealed) == b"legacy"


def test_unknown_format_rejected():
    with pytest.raises(crypto.CryptoError):
        crypto.unseal(b"garbage-data-here")


def test_tamper_detected(sandbox):
    if IS_WIN:
        pytest.skip("DPAPI 已有自身完整性校验，此用例针对 SHAKE+HMAC 分支")
    sealed = bytearray(crypto.seal(b"important"))
    sealed[-1] ^= 0x01
    with pytest.raises(crypto.CryptoError):
        crypto.unseal(bytes(sealed))


def test_secure_write_permissions(sandbox):
    p = sandbox["home"] / "secret.bin"
    crypto.secure_write(str(p), b"x")
    assert p.read_bytes() == b"x"
    if not IS_WIN:
        assert oct(p.stat().st_mode & 0o777) == "0o600"
