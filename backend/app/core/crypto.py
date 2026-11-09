"""Authenticated encryption helpers for provider credentials.

Ciphertexts are versioned and use AES-256-GCM with a fresh 96-bit nonce.  No
function in this module logs secret material, ciphertext, or decryption errors.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import os
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_VERSION = "v1"
_NONCE_BYTES = 12
_DEFAULT_AAD = b"zhijing:model-provider-credential:v1"


class SecretCryptoError(ValueError):
    """Base class for safe credential-encryption failures."""


class InvalidMasterKeyError(SecretCryptoError):
    """Raised when the configured master key cannot be used."""


class SecretDecryptionError(SecretCryptoError):
    """Raised without exposing the stored value or master key."""


def _secret_value(value: Any) -> str | bytes:
    getter = getattr(value, "get_secret_value", None)
    return getter() if callable(getter) else value


def _decode_exact_key(encoded: str, *, encoding: str) -> bytes:
    try:
        if encoding == "base64":
            padding = "=" * (-len(encoded) % 4)
            decoded = base64.urlsafe_b64decode(encoded + padding)
        else:
            decoded = bytes.fromhex(encoded)
    except (ValueError, binascii.Error) as exc:
        raise InvalidMasterKeyError(f"RAG_MASTER_KEY has invalid {encoding} encoding") from exc
    if len(decoded) != 32:
        raise InvalidMasterKeyError("RAG_MASTER_KEY must decode to exactly 32 bytes")
    return decoded


def derive_aes_key(master_key: str | bytes | Any) -> bytes:
    """Return a 32-byte AES key from a secret settings value.

    ``base64:`` and ``hex:`` forms must encode exactly 32 bytes.  A plain
    passphrase is domain-separated and expanded with SHA-256, which also keeps
    the development settings default usable.  Production settings separately
    reject the development default.
    """

    raw = _secret_value(master_key)
    if isinstance(raw, bytes):
        if not raw:
            raise InvalidMasterKeyError("RAG_MASTER_KEY must not be empty")
        return raw if len(raw) == 32 else hashlib.sha256(_DEFAULT_AAD + b"\0" + raw).digest()
    if not isinstance(raw, str):
        raise InvalidMasterKeyError("RAG_MASTER_KEY must be text or bytes")
    if not raw:
        raise InvalidMasterKeyError("RAG_MASTER_KEY must not be empty")
    if raw.startswith("base64:"):
        return _decode_exact_key(raw.removeprefix("base64:"), encoding="base64")
    if raw.startswith("hex:"):
        return _decode_exact_key(raw.removeprefix("hex:"), encoding="hex")
    return hashlib.sha256(_DEFAULT_AAD + b"\0" + raw.encode("utf-8")).digest()


def _aad_bytes(aad: str | bytes | None) -> bytes:
    if aad is None:
        return _DEFAULT_AAD
    return aad.encode("utf-8") if isinstance(aad, str) else aad


class CredentialCipher:
    """AES-GCM credential cipher safe to keep as an application singleton."""

    __slots__ = ("_aesgcm",)

    def __init__(self, master_key: str | bytes | Any) -> None:
        self._aesgcm = AESGCM(derive_aes_key(master_key))

    def __repr__(self) -> str:
        return "CredentialCipher(<redacted>)"

    @classmethod
    def from_settings(cls, app_settings: Any | None = None) -> CredentialCipher:
        """Create a cipher from ``Settings.master_key`` (``RAG_MASTER_KEY``)."""

        if app_settings is None:
            from app.core.config import get_settings

            app_settings = get_settings()
        return cls(app_settings.master_key)

    def encrypt(self, plaintext: str, *, aad: str | bytes | None = None) -> str:
        if not isinstance(plaintext, str) or not plaintext:
            raise SecretCryptoError("secret must be a non-empty string")
        nonce = os.urandom(_NONCE_BYTES)
        ciphertext = self._aesgcm.encrypt(nonce, plaintext.encode("utf-8"), _aad_bytes(aad))
        token = base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii").rstrip("=")
        return f"{_VERSION}:{token}"

    def decrypt(self, token: str, *, aad: str | bytes | None = None) -> str:
        try:
            version, encoded = token.split(":", maxsplit=1)
            if version != _VERSION or not encoded:
                raise ValueError
            padding = "=" * (-len(encoded) % 4)
            payload = base64.urlsafe_b64decode(encoded + padding)
            if len(payload) <= _NONCE_BYTES + 16:
                raise ValueError
            nonce, ciphertext = payload[:_NONCE_BYTES], payload[_NONCE_BYTES:]
            plaintext = self._aesgcm.decrypt(nonce, ciphertext, _aad_bytes(aad))
            return plaintext.decode("utf-8")
        except (AttributeError, UnicodeDecodeError, ValueError, binascii.Error, InvalidTag) as exc:
            raise SecretDecryptionError("Unable to decrypt stored credential") from exc


def mask_secret(secret: str | Any | None, *, prefix: int = 4, suffix: int = 4) -> str | None:
    """Return a stable display mask without retaining the full credential."""

    if secret is None:
        return None
    raw = _secret_value(secret)
    if not isinstance(raw, str):
        raise TypeError("secret must be a string")
    if not raw:
        return ""
    if len(raw) <= prefix + suffix:
        return "*" * min(len(raw), 8)
    return f"{raw[:prefix]}{'*' * 8}{raw[-suffix:]}"


def encrypt_api_key(api_key: str | Any, master_key: str | bytes | Any) -> str:
    """Convenience wrapper for persistence services."""

    raw = _secret_value(api_key)
    if not isinstance(raw, str):
        raise TypeError("api_key must be a string")
    return CredentialCipher(master_key).encrypt(raw)


def decrypt_api_key(encrypted_api_key: str, master_key: str | bytes | Any) -> str:
    """Convenience wrapper for persistence services."""

    return CredentialCipher(master_key).decrypt(encrypted_api_key)


mask_api_key = mask_secret
