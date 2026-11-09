import pytest

from app.core.crypto import CredentialCipher, SecretDecryptionError, mask_secret


def test_credential_cipher_round_trip_and_random_nonce() -> None:
    cipher = CredentialCipher("test-master-key")
    first = cipher.encrypt("sk-secret-value")
    second = cipher.encrypt("sk-secret-value")
    assert first != second
    assert cipher.decrypt(first) == "sk-secret-value"
    assert "secret" not in repr(cipher)


def test_credential_cipher_rejects_tampering() -> None:
    cipher = CredentialCipher("test-master-key")
    token = cipher.encrypt("sk-secret-value")
    with pytest.raises(SecretDecryptionError):
        cipher.decrypt(token[:-2] + "xx")


def test_mask_secret_never_returns_full_long_key() -> None:
    assert mask_secret("sk-1234567890abcdef") == "sk-1********cdef"
