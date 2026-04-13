"""Tests for agent.reporter -- API client."""

from unittest.mock import patch, MagicMock

import pytest

from agent.collector import CommitMetadata
from agent.reporter import Reporter


@pytest.fixture
def reporter(tmp_path):
    queue_file = str(tmp_path / "queue.json")
    return Reporter(
        api_url="http://localhost:8400/api/v1",
        api_token="sk-test-token",
        queue_file=queue_file,
    )


@pytest.fixture
def sample_metadata():
    return CommitMetadata(
        commit_hash="abc123def456",
        commit_message="Test commit",
        commit_author="dev@example.com",
        commit_timestamp="2026-04-10T12:00:00+00:00",
        files_changed=3,
        branch="main",
        previous_commit_hash="old123hash",
    )


class TestReporter:
    @patch("agent.reporter.requests.post")
    def test_send_event_success(self, mock_post, reporter, sample_metadata):
        mock_post.return_value = MagicMock(status_code=201)

        result = reporter.send_event(
            server_id="test-01",
            environment="staging",
            repo_alias="test-app",
            metadata=sample_metadata,
        )

        assert result is True
        assert mock_post.called

    @patch("agent.reporter.requests.post")
    def test_send_event_queues_on_failure(self, mock_post, reporter, sample_metadata):
        import requests
        mock_post.side_effect = requests.ConnectionError("refused")

        result = reporter.send_event(
            server_id="test-01",
            environment="staging",
            repo_alias="test-app",
            metadata=sample_metadata,
        )

        assert result is False
        assert reporter.queue.size() == 1

    @patch("agent.reporter.requests.post")
    def test_send_heartbeat_success(self, mock_post, reporter):
        mock_post.return_value = MagicMock(status_code=200)

        result = reporter.send_heartbeat(
            server_id="test-01",
            environment="staging",
            repos=["app-a", "app-b"],
            agent_version="0.1.0",
        )

        assert result is True

    @patch("agent.reporter.requests.post")
    def test_duplicate_event_treated_as_success(self, mock_post, reporter, sample_metadata):
        mock_post.return_value = MagicMock(status_code=409)

        result = reporter.send_event(
            server_id="test-01",
            environment="staging",
            repo_alias="test-app",
            metadata=sample_metadata,
        )

        assert result is True
        assert reporter.queue.size() == 0
