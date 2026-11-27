from agys import identity


def test_extract_email():
    blob = b'{"auth_method":"oauth","token":{"refresh_token":"r1","email":"Alice@Gmail.com"}}'
    assert identity.extract(blob) == "email:alice@gmail.com"


def test_refresh_does_not_change_identity():
    a = b'{"token":{"refresh_token":"OLD","email":"alice@gmail.com"}}'
    b = b'{"token":{"refresh_token":"NEW-ROTATED","email":"alice@gmail.com"}}'
    assert identity.extract(a) == identity.extract(b)


def test_sub_claim():
    blob = b'{"token":{"sub":"1234567890","refresh_token":"r"}}'
    assert identity.extract(blob) == "sub:1234567890"


def test_fallback_to_ga():
    assert identity.extract(b"not-json", {"active": "bob@gmail.com"}) == "email:bob@gmail.com"


def test_fallback_to_refresh_fingerprint():
    x = identity.extract(b'{"token":{"refresh_token":"abcdef"}}')
    assert x.startswith("rt:")
    assert x == identity.extract(b'{"token":{"refresh_token":"abcdef"}}')


def test_email_of_and_short():
    assert identity.email_of("email:a@b.com") == "a@b.com"
    assert identity.email_of("sub:123") == ""
    assert identity.short("email:a@b.com") == "a@b.com"


# ---------------------------------------------------------------- token 过期

def test_token_expiry_none():
    assert identity.token_expiry(b'{"token":{"refresh_token":"r"}}') is None
    assert identity.token_expiry(b"not-json") is None


def test_token_expiry_epoch_seconds():
    blob = b'{"token":{"expiry": 1799000000}}'
    got = identity.token_expiry(blob)
    assert got is not None and (got.startswith("2026-") or got.startswith("2027-"))


def test_token_expiry_epoch_millis():
    blob = b'{"token":{"expiry": 1799000000000}}'
    assert identity.token_expiry(blob) == identity.token_expiry(
        b'{"token":{"expiry": 1799000000}}')


def test_token_expiry_iso_passthrough():
    blob = b'{"token":{"expiry": "2026-12-01T00:00:00Z"}}'
    assert identity.token_expiry(blob) == "2026-12-01T00:00:00Z"


def test_expiry_age_future_and_past():
    future = "2099-01-01T00:00:00Z"
    assert identity.expiry_age(future) > 0
    past = "2000-01-01T00:00:00Z"
    assert identity.expiry_age(past) < 0
    assert identity.expiry_age("not-a-date") is None
    assert identity.expiry_age(None) is None


def test_expiry_human():
    assert "已过期" in identity.expiry_human("2000-01-01T00:00:00Z")
    assert identity.expiry_human("not-a-date") == ""
    assert "小时" in identity.expiry_human("2099-01-01T00:00:00Z") or \
        "天" in identity.expiry_human("2099-01-01T00:00:00Z")
