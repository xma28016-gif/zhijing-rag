from datetime import UTC, datetime

from app.schemas.api_key import ApiKeyCreate
from app.services.api_keys import hash_api_key


def test_api_key_hash_is_deterministic_and_does_not_contain_secret() -> None:
    secret = "rag_super-secret"
    digest = hash_api_key(secret)
    assert digest == hash_api_key(secret)
    assert secret not in digest
    assert len(digest) == 64


def test_api_key_expiry_is_normalized_to_utc() -> None:
    payload = ApiKeyCreate(
        name="integration",
        allow_all_assistants=True,
        expires_at=datetime(2030, 1, 1),
    )
    assert payload.expires_at and payload.expires_at.tzinfo is UTC
