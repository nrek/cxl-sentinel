"""Local state file management for tracking last-seen commit hashes."""

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("sentinel.state")


class StateManager:
    """Manages a JSON state file that maps project names to their last-seen commit hash."""

    def __init__(self, state_file: str):
        self.state_file = Path(state_file)
        self._state: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if not self.state_file.exists():
            logger.info("State file does not exist, starting fresh: %s", self.state_file)
            self._state = {}
            return

        try:
            with open(self.state_file, "r") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError(f"Expected dict, got {type(data).__name__}")
            self._state = data
            logger.debug("Loaded state with %d entries", len(self._state))
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("Corrupt state file, resetting: %s", e)
            self._state = {}

    def save(self) -> None:
        """Write current state to disk. Creates parent directories if needed."""
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.state_file.with_suffix(".tmp")
            with open(tmp, "w") as f:
                json.dump(self._state, f, indent=2)
            tmp.replace(self.state_file)
            logger.debug("State saved: %d entries", len(self._state))
        except OSError as e:
            logger.error("Failed to save state file: %s", e)

    def get_last_hash(self, project_name: str) -> Optional[str]:
        """Return the last-seen commit hash for a project, or None."""
        return self._state.get(project_name)

    def set_last_hash(self, project_name: str, commit_hash: str) -> None:
        """Update the last-seen commit hash for a project."""
        self._state[project_name] = commit_hash

    def all_entries(self) -> dict[str, str]:
        """Return a copy of all state entries."""
        return dict(self._state)
