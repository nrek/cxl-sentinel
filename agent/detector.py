"""Git change detection -- compares current HEAD against stored state."""

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger("sentinel.detector")


@dataclass
class DetectionResult:
    changed: bool
    current_hash: str
    previous_hash: Optional[str]
    branch: str
    error: Optional[str] = None


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


def detect_change(project_path: str, branch: str, last_known_hash: Optional[str]) -> DetectionResult:
    """Check if the HEAD of a project has changed since last_known_hash.

    Args:
        project_path: Absolute path to the git repository.
        branch: Expected branch name (used for logging; detection is based on HEAD).
        last_known_hash: The commit hash from the last scan, or None for first run.

    Returns:
        DetectionResult with change status and commit hashes.
    """
    path = Path(project_path)

    if not path.exists():
        return DetectionResult(
            changed=False, current_hash="", previous_hash=last_known_hash,
            branch=branch, error=f"Path does not exist: {project_path}",
        )

    git_dir = path / ".git"
    if not git_dir.exists():
        return DetectionResult(
            changed=False, current_hash="", previous_hash=last_known_hash,
            branch=branch, error=f"Not a git repository: {project_path}",
        )

    stdout, stderr, rc = _run_git(["rev-parse", "HEAD"], cwd=project_path)
    if rc != 0:
        return DetectionResult(
            changed=False, current_hash="", previous_hash=last_known_hash,
            branch=branch, error=f"git rev-parse HEAD failed: {stderr}",
        )

    current_hash = stdout

    if last_known_hash is None:
        logger.info("First scan for %s, recording HEAD %s", project_path, current_hash[:12])
        return DetectionResult(
            changed=False, current_hash=current_hash,
            previous_hash=None, branch=branch,
        )

    if current_hash == last_known_hash:
        return DetectionResult(
            changed=False, current_hash=current_hash,
            previous_hash=last_known_hash, branch=branch,
        )

    logger.info(
        "Change detected in %s: %s -> %s",
        project_path, last_known_hash[:12], current_hash[:12],
    )
    return DetectionResult(
        changed=True, current_hash=current_hash,
        previous_hash=last_known_hash, branch=branch,
    )


def get_current_branch(project_path: str) -> Optional[str]:
    """Return the current branch name, or None if detached or on error."""
    stdout, stderr, rc = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=project_path)
    if rc != 0 or stdout == "HEAD":
        return None
    return stdout
