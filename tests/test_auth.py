"""Phase 3 acceptance: /api/v1/auth/login + /refresh against real PostgreSQL."""

from app.core.security import decode_token


class TestLogin:
    async def test_login_success_returns_pair(self, client, make_user):
        await make_user(email="alice@test.com", password="password123")
        r = client.post(
            "/api/v1/auth/login", json={"email": "alice@test.com", "password": "password123"}
        )
        assert r.status_code == 200
        body = r.json()
        assert body["token_type"] == "bearer"
        assert body["expires_in"] == 30 * 60
        assert decode_token(body["access_token"], expected_type="access") >= 1
        assert decode_token(body["refresh_token"], expected_type="refresh") >= 1

    async def test_login_wrong_password_401(self, client, make_user):
        await make_user(email="bob@test.com", password="password123")
        r = client.post(
            "/api/v1/auth/login", json={"email": "bob@test.com", "password": "wrong-pass-1"}
        )
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "invalid_credentials"

    async def test_login_unknown_email_401_identical_error(self, client, make_user):
        """No user enumeration: same code + message as wrong password (decision #3)."""
        await make_user(email="known@test.com", password="password123")
        r_unknown = client.post(
            "/api/v1/auth/login", json={"email": "ghost@test.com", "password": "password123"}
        )
        r_wrong = client.post(
            "/api/v1/auth/login", json={"email": "known@test.com", "password": "wrong-pass-1"}
        )
        assert r_unknown.status_code == 401
        assert r_unknown.json() == r_wrong.json()

    async def test_login_invalid_body_422(self, client):
        r = client.post(
            "/api/v1/auth/login", json={"email": "not-an-email", "password": "short"}
        )
        assert r.status_code == 422
        body = r.json()["error"]
        assert body["code"] == "validation_error"
        fields = {d["field"] for d in body["details"]}
        assert {"email", "password"} <= fields


class TestRefresh:
    async def test_refresh_exchanges_for_new_pair(self, client, make_user):
        await make_user(email="carol@test.com", password="password123")
        login = client.post(
            "/api/v1/auth/login", json={"email": "carol@test.com", "password": "password123"}
        ).json()
        old_access = login["access_token"]

        r = client.post("/api/v1/auth/refresh", json={"refresh_token": login["refresh_token"]})
        assert r.status_code == 200
        new = r.json()
        # Same subject, fresh validity window (tokens issued within the same second
        # are byte-identical, so assert on the decoded subject, not string inequality)
        assert decode_token(new["access_token"], expected_type="access") == decode_token(
            old_access, expected_type="access"
        )
        assert decode_token(new["refresh_token"], expected_type="refresh") >= 1

    async def test_refresh_rejects_access_token(self, client, make_user):
        """Type separation: an access token is never a refresh token (decision #3)."""
        await make_user(email="dave@test.com", password="password123")
        login = client.post(
            "/api/v1/auth/login", json={"email": "dave@test.com", "password": "password123"}
        ).json()
        r = client.post("/api/v1/auth/refresh", json={"refresh_token": login["access_token"]})
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "invalid_credentials"

    async def test_refresh_rejects_garbage(self, client):
        r = client.post("/api/v1/auth/refresh", json={"refresh_token": "garbage.token.here"})
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "invalid_credentials"
