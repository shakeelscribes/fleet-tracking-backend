"""Unit tests for security primitives and the error envelope (Phase 2 gate)."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.exceptions import (
    AppError,
    ConflictError,
    CredentialsError,
    ForbiddenError,
    NoAssignmentError,
    NotFoundError,
    register_exception_handlers,
)
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)

# --- Password hashing (decision #3) -----------------------------------------


class TestPasswordHashing:
    def test_hash_and_verify_roundtrip(self):
        hashed = hash_password("s3cret-password")
        assert hashed != "s3cret-password"
        assert hashed.startswith("$argon2")

    def test_verify_correct_password(self):
        assert verify_password("s3cret-password", hash_password("s3cret-password")) is True

    def test_verify_wrong_password(self):
        assert verify_password("wrong", hash_password("s3cret-password")) is False

    def test_hashes_are_salted(self):
        assert hash_password("same") != hash_password("same")


# --- JWT lifecycle (decision #3) ---------------------------------------------


class TestJwtTokens:
    def test_access_token_roundtrip(self):
        token = create_access_token(user_id=42)
        assert decode_token(token, expected_type="access") == 42

    def test_refresh_token_roundtrip(self):
        token = create_refresh_token(user_id=7)
        assert decode_token(token, expected_type="refresh") == 7

    def test_type_mismatch_rejected(self):
        # A refresh token must never pass as an access token
        refresh = create_refresh_token(user_id=1)
        with pytest.raises(CredentialsError):
            decode_token(refresh, expected_type="access")

    def test_expired_token_rejected(self, monkeypatch):
        monkeypatch.setattr("app.core.security.settings.ACCESS_TOKEN_EXPIRE_MINUTES", -1)
        expired = create_access_token(user_id=1)
        with pytest.raises(CredentialsError, match="expired"):
            decode_token(expired, expected_type="access")

    def test_garbage_token_rejected(self):
        with pytest.raises(CredentialsError):
            decode_token("not.a.jwt", expected_type="access")

    def test_tampered_signature_rejected(self):
        token = create_access_token(user_id=1)
        with pytest.raises(CredentialsError):
            decode_token(token[:-3] + "xyz", expected_type="access")


# --- Error envelope (decision #13) -------------------------------------------

@pytest.mark.parametrize(
    ("exc", "status", "code"),
    [
        (CredentialsError("bad"), 401, "invalid_credentials"),
        (ForbiddenError("no"), 403, "forbidden"),
        (NoAssignmentError("none"), 403, "no_assignment"),
        (NotFoundError("gone"), 404, "not_found"),
        (ConflictError("dup"), 409, "conflict"),
        (AppError("boom"), 500, "internal_error"),
    ],
)
def test_error_envelope(exc, status, code):
    probe = FastAPI()
    register_exception_handlers(probe)

    @probe.get("/boom")
    def _boom():
        raise exc

    with TestClient(probe, raise_server_exceptions=False) as c:
        r = c.get("/boom")
    assert r.status_code == status
    assert r.json()["error"]["code"] == code
    assert isinstance(r.json()["error"]["message"], str)


def test_unknown_route_uses_envelope(client):
    r = client.get("/definitely-not-a-route")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


def test_validation_error_envelope():
    probe = FastAPI()
    register_exception_handlers(probe)

    @probe.get("/q")
    def _q(limit: int):  # noqa: ARG001 - intentionally empty probe endpoint
        return {"limit": limit}

    with TestClient(probe) as c:
        r = c.get("/q", params={"limit": "not-a-number"})
    body = r.json()["error"]
    assert r.status_code == 422
    assert body["code"] == "validation_error"
    assert body["details"][0]["field"] == "limit"
