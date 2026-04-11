"""Commit metadata collection from git repositories.

Gathers aggregate deploy-level data: how many commits were included,
which contributors participated, total files changed, and the latest
commit details. This powers the executive-level notification emails.
"""

import logging
import subprocess
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("sentinel.collector")


@dataclass
class CommitMetadata:
    commit_hash: str
    commit_message: str
    commit_author: str
    commit_timestamp: str  # ISO 8601
    files_changed: int
    branch: str
    previous_commit_hash: Optional[str]
    commit_count: int = 1
    contributors: list[str] = field(default_factory=list)


def _run_git(args: list[str], cwd: str, timeout: int = 30) -> tuple[str, str, int]:
    """Run a git command and return (stdout, stderr, returncode)."""
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except subprocess.TimeoutExpired:
        return "", "git command timed out", -1
    except FileNotFoundError:
        return "", "git is not installed or not on PATH", -1


def collect_commit_metadata(
    project_path: str,
    current_hash: str,
    previous_hash: Optional[str],
    branch: str,
) -> Optional[CommitMetadata]:
    """Collect aggregate metadata for all changes between previous_hash and current_hash.

    Captures the latest commit's details plus summary stats across the
    full range: commit count, unique contributors, and total files changed.
    """
    fmt = "%H%n%ae%n%s%n%aI"
    stdout, stderr, rc = _run_git(
        ["log", "-1", f"--format={fmt}", current_hash],
        cwd=project_path,
    )

    if rc != 0:
        logger.error("Failed to read commit %s in %s: %s", current_hash[:12], project_path, stderr)
        return None

    lines = stdout.split("\n", 3)
    if len(lines) < 4:
        logger.error("Unexpected git log output for %s: %s", current_hash[:12], stdout)
        return None

    commit_hash, author, message, timestamp_str = lines[0], lines[1], lines[2], lines[3]

    files_changed = _count_files_changed(project_path, current_hash, previous_hash)
    commit_count, contributors = _collect_range_stats(project_path, current_hash, previous_hash)

    if not contributors:
        contributors = [author]

    return CommitMetadata(
        commit_hash=commit_hash,
        commit_message=message,
        commit_author=author,
        commit_timestamp=timestamp_str,
        files_changed=files_changed,
        branch=branch,
        previous_commit_hash=previous_hash,
        commit_count=commit_count,
        contributors=contributors,
    )


def _collect_range_stats(
    project_path: str,
    current_hash: str,
    previous_hash: Optional[str],
) -> tuple[int, list[str]]:
    """Count commits and unique contributors between two hashes.

    Returns (commit_count, sorted list of unique author emails).
    """
    if previous_hash:
        rev_range = f"{previous_hash}..{current_hash}"
    else:
        rev_range = current_hash

    stdout, stderr, rc = _run_git(
        ["log", "--format=%ae", rev_range],
        cwd=project_path,
    )

    if rc != 0 or not stdout:
        return 1, []

    authors = stdout.strip().split("\n")
    commit_count = len(authors)
    unique_authors = sorted(set(a.strip() for a in authors if a.strip()))

    return commit_count, unique_authors


def _count_files_changed(project_path: str, current_hash: str, previous_hash: Optional[str]) -> int:
    """Count the number of files changed between two commits, or in the latest commit."""
    if previous_hash:
        stdout, stderr, rc = _run_git(
            ["diff", "--name-only", previous_hash, current_hash],
            cwd=project_path,
        )
    else:
        stdout, stderr, rc = _run_git(
            ["diff-tree", "--no-commit-id", "--name-only", "-r", current_hash],
            cwd=project_path,
        )

    if rc != 0:
        logger.warning("Could not count changed files: %s", stderr)
        return 0

    if not stdout:
        return 0

    return len(stdout.strip().split("\n"))
