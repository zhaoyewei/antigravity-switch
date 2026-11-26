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
