"""Tests for agent.detector -- git change detection."""

import subprocess
from unittest.mock import patch, MagicMock

import pytest

from agent.detector import detect_change, get_current_branch, DetectionResult


@pytest.fixture
def git_repo(tmp_path):
    """Create a minimal git repo with one commit."""
    repo = tmp_path / "test-repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, capture_output=True)
    (repo / "file.txt").write_text("hello")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True)
    return repo


class TestDetectChange:
    def test_first_scan_records_hash(self, git_repo):
        result = detect_change(str(git_repo), "main", last_known_hash=None)
        assert not result.changed
        assert len(result.current_hash) == 40
        assert result.previous_hash is None
        assert result.error is None

    def test_no_change(self, git_repo):
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=git_repo,
            capture_output=True, text=True,
        ).stdout.strip()

        result = detect_change(str(git_repo), "main", last_known_hash=head)
        assert not result.changed
        assert result.current_hash == head

    def test_detects_new_commit(self, git_repo):
        old_head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=git_repo,
            capture_output=True, text=True,
        ).stdout.strip()

        (git_repo / "file2.txt").write_text("world")
        subprocess.run(["git", "add", "."], cwd=git_repo, capture_output=True)
        subprocess.run(["git", "commit", "-m", "second"], cwd=git_repo, capture_output=True)

        result = detect_change(str(git_repo), "main", last_known_hash=old_head)
        assert result.changed
        assert result.current_hash != old_head
        assert result.previous_hash == old_head

    def test_nonexistent_path(self):
        result = detect_change("/nonexistent/path", "main", last_known_hash=None)
        assert not result.changed
        assert result.error is not None
        assert "does not exist" in result.error

    def test_not_a_git_repo(self, tmp_path):
        plain_dir = tmp_path / "not-git"
        plain_dir.mkdir()
        result = detect_change(str(plain_dir), "main", last_known_hash=None)
        assert not result.changed
        assert result.error is not None
        assert "Not a git repository" in result.error


class TestGetCurrentBranch:
    def test_returns_branch_name(self, git_repo):
        branch = get_current_branch(str(git_repo))
        assert branch in ("main", "master")

    def test_returns_none_for_bad_path(self):
        branch = get_current_branch("/nonexistent")
        assert branch is None
