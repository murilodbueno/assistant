import hashlib
import hmac

from assistant.whatsapp import verify_hmac


def test_verify_hmac_valid():
    secret = "fake-hmac-key"
    body = b'{"event":"message"}'
    sig = hmac.new(secret.encode(), body, hashlib.sha512).hexdigest()
    assert verify_hmac(body, sig, secret)
    assert verify_hmac(body, f"sha512={sig}", secret)


def test_verify_hmac_invalid():
    assert not verify_hmac(b"{}", "bad-signature", "fake-hmac-key")
    assert not verify_hmac(b"{}", "", "fake-hmac-key")
