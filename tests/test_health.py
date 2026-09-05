"""Phase 8 additions: lifespan coverage + auth hardening at the HTTP boundary."""

import jwt
import pytest
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient

from app import main as app_main
from app.core import security
from app.core.config import settings
from app.core.deps import get_current_user
from app.core.exceptions import CredentialsError


def test_health_lifespan_runs_with_mqtt_disabled():
    """Raw-ASGI entry into the app so the lifespan (MQTT-disabled branch) executes."""
    with TestClient(app_main.app) as c:
        r = c.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_access_token_with_malformed_subject_rejected_over_http(client):
    """JWTs whose `sub` cannot become an int must fail with 401, not 500."""
    token = jwt.encode({"type": "access"}, settings.JWT_SECRET_KEY, algorithm="HS256")
    r = client.get("/api/v1/me/assignment", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "invalid_credentials"


@pytest.mark.parametrize("header", ["", "Token abc", "Bearer", "Bearer "])
def test_malformed_authorization_headers_rejected(client, header):
    r = client.get(
        "/api/v1/me/assignment",
        headers={"Authorization": header} if header else None,
    )
    assert r.status_code in (401, 403)  # FastAPI: 403 for missing header, 401 for bad scheme


async def test_token_of_deleted_user_rejected(db, make_user):
    """A valid access token must die with its user (deps.get_current_user)."""
    user = await make_user(email="vanish@fleet.com")
    token = security.create_access_token(user.id)
    await db.delete(user)
    await db.commit()
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    with pytest.raises(CredentialsError, match="no longer exists"):
        await get_current_user(credentials=creds, db=db)

