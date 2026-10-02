from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

SESSION_TOKEN = "arena-test-token-not-a-secret"
ORIGIN = "http://127.0.0.1:8787"


def authenticated_client(app: FastAPI) -> TestClient:
    client = TestClient(app, base_url=ORIGIN)
    response = client.post("/api/session", json={"token": SESSION_TOKEN}, headers={"Origin": ORIGIN})
    assert response.status_code == 204
    return client
