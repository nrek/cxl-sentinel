"""Tests for agent.collector -- commit metadata extraction."""

import subprocess

import pytest

from agent.collector import collect_commit_metadata


@pytest.fixture
def git_repo(tmp_path):
    """Create a git repo with two commits."""
    repo = tmp_path / "test-repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True)
    subprocess.run(["git", "config", "user.email", "dev@example.com"], cwd=repo, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Dev"], cwd=repo, capture_output=True)

    (repo / "file1.txt").write_text("hello")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo, capture_output=True)

    first_hash = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo,
        capture_output=True, text=True,
    ).stdout.strip()

    (repo / "file2.txt").write_text("world")
    (repo / "file1.txt").write_text("updated")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Second commit"], cwd=repo, capture_output=True)

    second_hash = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo,
        capture_output=True, text=True,
    ).stdout.strip()

    return repo, first_hash, second_hash


class TestCollectCommitMetadata:
    def test_collects_metadata(self, git_repo):
        repo, first_hash, second_hash = git_repo
        meta = collect_commit_metadata(str(repo), second_hash, first_hash, "main")

        assert meta is not None
        assert meta.commit_hash == second_hash
        assert meta.commit_message == "Second commit"
        assert meta.commit_author == "dev@example.com"
        assert meta.commit_timestamp is not None
        assert meta.branch == "main"
        assert meta.previous_commit_hash == first_hash
        assert meta.files_changed == 2

    def test_first_commit_no_previous(self, git_repo):
        repo, first_hash, _ = git_repo
        meta = collect_commit_metadata(str(repo), first_hash, None, "main")

        assert meta is not None
        assert meta.commit_hash == first_hash
        assert meta.commit_message == "Initial commit"
        assert meta.previous_commit_hash is None
        assert meta.files_changed >= 1

    def test_invalid_hash_returns_none(self, git_repo):
        repo, _, _ = git_repo
        meta = collect_commit_metadata(str(repo), "deadbeef" * 5, None, "main")
        assert meta is None
