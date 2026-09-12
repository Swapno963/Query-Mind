from __future__ import annotations

import base64
import hashlib
import hmac
import os

from django.conf import settings


def _key() -> bytes:
    return hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()


def encrypt_secret(plain: str) -> str:
    raw = (plain or "").encode("utf-8")
    key = _key()
    nonce = os.urandom(16)
    xored = bytes(b ^ key[i % len(key)] for i, b in enumerate(raw))
    mac = hmac.new(key, nonce + xored, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(nonce + mac + xored).decode("ascii")


def decrypt_secret(token: str) -> str:
    data = base64.urlsafe_b64decode(token.encode("ascii"))
    nonce, mac, xored = data[:16], data[16:48], data[48:]
    key = _key()
    expected = hmac.new(key, nonce + xored, hashlib.sha256).digest()
    if not hmac.compare_digest(mac, expected):
        raise ValueError("Stored database password could not be decrypted.")
    raw = bytes(b ^ key[i % len(key)] for i, b in enumerate(xored))
    return raw.decode("utf-8")
