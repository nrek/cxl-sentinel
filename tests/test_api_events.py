"""Tests for the deploy events API endpoints."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.auth import hash_token
from api.database import get_session
from api.main import app
from api.models import ApiToken, Base


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    token = ApiToken(
        name="test-agent",
        token_hash=hash_token("sk-test-agent"),
        role="agent",
        is_active=True,
    )
    admin_token = ApiToken(
        name="test-admin",
        token_hash=hash_token("sk-test-admin"),
        role="admin",
        is_active=True,
    )
    session.add_all([token, admin_token])
    session.commit()

    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def client(db_session):
    def _override_session():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_session] = _override_session
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


SAMPLE_EVENT = {
    "server_id": "test-01",
    "environment": "staging",
    "repo_alias": "test-app",
    "commit_hash": "abc1234567890",
    "commit_message": "Test deploy",
    "commit_author": "dev@example.com",
    "commit_timestamp": "2026-04-10T14:00:00Z",
    "previous_commit_hash": "def0987654321",
    "files_changed": 5,
    "branch": "main",
    "detected_at": "2026-04-10T14:02:00Z",
}


class TestCreateEvent:
    def test_create_event_success(self, client):
        resp = client.post(
            "/api/v1/events",
            json=SAMPLE_EVENT,
            headers={"Authorization": "Bearer sk-test-agent"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "recorded"
        assert "id" in data

    def test_duplicate_event_returns_409(self, client):
        headers = {"Authorization": "Bearer sk-test-agent"}
        client.post("/api/v1/events", json=SAMPLE_EVENT, headers=headers)
        resp = client.post("/api/v1/events", json=SAMPLE_EVENT, headers=headers)
        assert resp.status_code == 409

    def test_missing_auth_returns_403(self, client):
        resp = client.post("/api/v1/events", json=SAMPLE_EVENT)
        assert resp.status_code == 403

    def test_invalid_token_returns_401(self, client):
        resp = client.post(
            "/api/v1/events",
            json=SAMPLE_EVENT,
            headers={"Authorization": "Bearer sk-invalid"},
        )
        assert resp.status_code == 401

    def test_invalid_environment_returns_422(self, client):
        bad = {**SAMPLE_EVENT, "environment": "dev"}
        resp = client.post(
            "/api/v1/events",
            json=bad,
            headers={"Authorization": "Bearer sk-test-agent"},
        )
        assert resp.status_code == 422


class TestListEvents:
    def test_list_events_requires_admin(self, client):
        resp = client.get(
            "/api/v1/events",
            headers={"Authorization": "Bearer sk-test-agent"},
        )
        assert resp.status_code == 403

    def test_list_events_as_admin(self, client):
        headers_agent = {"Authorization": "Bearer sk-test-agent"}
        headers_admin = {"Authorization": "Bearer sk-test-admin"}

        client.post("/api/v1/events", json=SAMPLE_EVENT, headers=headers_agent)

        resp = client.get("/api/v1/events", headers=headers_admin)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["repo_alias"] == "test-app"

    def test_filter_by_repo_alias(self, client):
        headers_agent = {"Authorization": "Bearer sk-test-agent"}
        headers_admin = {"Authorization": "Bearer sk-test-admin"}

        client.post("/api/v1/events", json=SAMPLE_EVENT, headers=headers_agent)

        resp = client.get("/api/v1/events?repo_alias=nonexistent", headers=headers_admin)
        assert resp.status_code == 200
        assert len(resp.json()) == 0
