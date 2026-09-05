"""Phase 0 acceptance: app boots and /health responds."""


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
