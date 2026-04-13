"""Tests for API authentication and authorization."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.auth import hash_token, generate_token
from api.database import get_session
from api.main import app
from api.models import ApiToken, Base


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    session.add_all([
        ApiToken(name="agent-1", token_hash=hash_token("sk-agent-1"), role="agent", is_active=True),
        ApiToken(name="admin-1", token_hash=hash_token("sk-admin-1"), role="admin", is_active=True),
        ApiToken(name="reader-1", token_hash=hash_token("sk-reader-1"), role="readonly", is_active=True),
        ApiToken(name="revoked", token_hash=hash_token("sk-revoked"), role="agent", is_active=False),
    ])
    session.commit()

    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def client(db_session):
    def _override():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_session] = _override
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


class TestAuthentication:
    def test_valid_agent_token(self, client):
        resp = client.post(
            "/api/v1/heartbeat",
            json={
                "server_id": "test-01",
                "environment": "production",
                "repos_watched": [],
                "agent_version": "0.1.0",
            },
            headers={"Authorization": "Bearer sk-agent-1"},
        )
        assert resp.status_code == 200

    def test_revoked_token_rejected(self, client):
        resp = client.post(
            "/api/v1/heartbeat",
            json={
                "server_id": "test-01",
                "environment": "production",
                "repos_watched": [],
            },
            headers={"Authorization": "Bearer sk-revoked"},
        )
        assert resp.status_code == 401

    def test_no_auth_header(self, client):
        resp = client.get("/api/v1/servers")
        assert resp.status_code == 403

    def test_health_no_auth_required(self, client):
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "healthy"


class TestAuthorization:
    def test_agent_cannot_list_events(self, client):
        resp = client.get(
            "/api/v1/events",
            headers={"Authorization": "Bearer sk-agent-1"},
        )
        assert resp.status_code == 403

    def test_admin_can_list_events(self, client):
        resp = client.get(
            "/api/v1/events",
            headers={"Authorization": "Bearer sk-admin-1"},
        )
        assert resp.status_code == 200

    def test_readonly_can_list_events(self, client):
        resp = client.get(
            "/api/v1/events",
            headers={"Authorization": "Bearer sk-reader-1"},
        )
        assert resp.status_code == 200

    def test_readonly_cannot_post_events(self, client):
        resp = client.post(
            "/api/v1/events",
            json={
                "server_id": "x", "environment": "staging",
                "repo_alias": "x", "commit_hash": "abc1234", "branch": "main",
                "detected_at": "2026-04-10T12:00:00Z",
            },
            headers={"Authorization": "Bearer sk-reader-1"},
        )
        assert resp.status_code == 403


class TestTokenGeneration:
    def test_generated_token_format(self):
        token = generate_token()
        assert token.startswith("sk-")
        assert len(token) > 20

    def test_hash_is_deterministic(self):
        h1 = hash_token("test-token")
        h2 = hash_token("test-token")
        assert h1 == h2

    def test_different_tokens_different_hashes(self):
        h1 = hash_token("token-a")
        h2 = hash_token("token-b")
        assert h1 != h2
