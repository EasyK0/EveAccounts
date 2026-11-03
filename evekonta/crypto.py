"""Encryption of passwords and tokens.

On Windows data is encrypted with DPAPI (the Windows account key) plus extra
"entropy" derived from the app's master password. Reading the vault needs both
your Windows account *and* the master password.

Outside Windows (tests/development only) a simple SHA-256 stream cipher + HMAC
keyed by the master password is used.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import sys

from .i18n import tr

PBKDF2_ITERATIONS = 300_000


class WrongPassword(Exception):
    pass


def new_salt() -> bytes:
    return os.urandom(16)


def derive_key(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)


def verifier_for(key: bytes) -> str:
    return hashlib.sha256(b"evekonta-verify" + key).hexdigest()


class Vault:
    """Encrypts/decrypts text with a key derived from the master password."""

    def __init__(self, key: bytes, *, use_dpapi: bool | None = None):
        self._key = key
        self._dpapi = (sys.platform == "win32") if use_dpapi is None else use_dpapi

    @classmethod
    def unlock(cls, password: str, salt: bytes, verifier: str) -> Vault:
        key = derive_key(password, salt)
        if not hmac.compare_digest(verifier_for(key), verifier):
            raise WrongPassword(tr("Wrong master password"))
        return cls(key)

    def encrypt(self, text: str | None) -> bytes | None:
        if text is None or text == "":
            return None
        data = text.encode("utf-8")
        if self._dpapi:
            return b"D1" + _dpapi_protect(data, self._key)
        return b"F1" + _fallback_encrypt(data, self._key)

    def decrypt(self, blob: bytes | None) -> str:
        if not blob:
            return ""
        blob = bytes(blob)
        tag, body = blob[:2], blob[2:]
        if tag == b"D1":
            return _dpapi_unprotect(body, self._key).decode("utf-8")
        if tag == b"F1":
            return _fallback_decrypt(body, self._key).decode("utf-8")
        raise ValueError(tr("Unknown encrypted data format"))


# --- fallback (non-Windows) -------------------------------------------------


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < length:
        out += hashlib.sha256(key + nonce + counter.to_bytes(8, "big")).digest()
        counter += 1
    return bytes(out[:length])


def _fallback_encrypt(data: bytes, key: bytes) -> bytes:
    nonce = os.urandom(16)
    ct = bytes(a ^ b for a, b in zip(data, _keystream(key, nonce, len(data)), strict=True))
    tag = hmac.new(key, nonce + ct, hashlib.sha256).digest()
    return nonce + ct + tag


def _fallback_decrypt(body: bytes, key: bytes) -> bytes:
    nonce, ct, tag = body[:16], body[16:-32], body[-32:]
    if not hmac.compare_digest(tag, hmac.new(key, nonce + ct, hashlib.sha256).digest()):
        raise WrongPassword(tr("Damaged data or wrong master password"))
    return bytes(a ^ b for a, b in zip(ct, _keystream(key, nonce, len(ct)), strict=True))


# --- DPAPI (Windows) --------------------------------------------------------


def _dpapi_call(data: bytes, entropy: bytes, protect: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def blob(raw: bytes):
        buf = ctypes.create_string_buffer(raw, len(raw))
        return DATA_BLOB(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    in_blob, _in_buf = blob(data)
    ent_blob, _ent_buf = blob(entropy)
    out_blob = DATA_BLOB()
    CRYPTPROTECT_UI_FORBIDDEN = 0x1
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    ok = fn(
        ctypes.byref(in_blob),
        None,
        ctypes.byref(ent_blob),
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(out_blob),
    )
    if not ok:
        if protect:
            raise OSError(tr("DPAPI: encryption failed"))
        raise WrongPassword(tr("Cannot decrypt (different Windows account or wrong master password)"))
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


def _dpapi_protect(data: bytes, entropy: bytes) -> bytes:
    return _dpapi_call(data, entropy, True)


def _dpapi_unprotect(data: bytes, entropy: bytes) -> bytes:
    return _dpapi_call(data, entropy, False)
