"""YAML configuration loader and validation for the Sentinel agent."""

from dataclasses import dataclass, field
from pathlib import Path

import yaml


def parse_duration(value) -> int:
    """Parse '5m', '6h', '1d', '300' into seconds."""
    s = str(value).strip().lower()
    if s.endswith("m"):
        return int(s[:-1]) * 60
    if s.endswith("h"):
        return int(s[:-1]) * 3600
    if s.endswith("d"):
        return int(s[:-1]) * 86400
    if s.endswith("s"):
        return int(s[:-1])
    return int(s)


@dataclass
class RepoConfig:
    alias: str
    path: str
    branch: str = "main"

    def validate(self) -> list[str]:
        errors = []
        if not self.alias:
            errors.append("Repo alias is required")
        if not self.path:
            errors.append(f"Repo '{self.alias}': path is required")
        elif not Path(self.path).is_absolute():
            errors.append(f"Repo '{self.alias}': path must be absolute, got '{self.path}'")
        return errors


@dataclass
class SentinelConfig:
    api_url: str
    api_token: str
    server_id: str
    environment: str
    scan_interval: int = 300  # stored as seconds internally
    state_file: str = "/var/lib/sentinel/state.json"

    def validate(self) -> list[str]:
        errors = []
        if not self.api_url:
            errors.append("sentinel.api_url is required")
        if not self.api_token:
            errors.append("sentinel.api_token is required")
        if not self.server_id:
            errors.append("sentinel.server_id is required")
        if self.environment not in ("production", "staging"):
            errors.append(f"sentinel.environment must be 'production' or 'staging', got '{self.environment}'")
        if self.scan_interval < 60:
            errors.append(f"sentinel.scan_interval must be >= 60 seconds (1m), got {self.scan_interval}")
        return errors


@dataclass
class LoggingConfig:
    level: str = "INFO"
    file: str = "/var/log/sentinel/agent.log"
    max_bytes: int = 10_485_760
    backup_count: int = 5

    def validate(self) -> list[str]:
        errors = []
        valid_levels = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
        if self.level.upper() not in valid_levels:
            errors.append(f"logging.level must be one of {valid_levels}, got '{self.level}'")
        return errors


@dataclass
class AgentConfig:
    sentinel: SentinelConfig
    repos: list[RepoConfig] = field(default_factory=list)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    def validate(self) -> list[str]:
        errors = self.sentinel.validate()
        errors.extend(self.logging.validate())
        if not self.repos:
            errors.append("At least one repo must be configured")
        for repo in self.repos:
            errors.extend(repo.validate())
        return errors


def load_config(path: str) -> AgentConfig:
    """Load and validate agent configuration from a YAML file.

    Raises:
        FileNotFoundError: If the config file does not exist.
        ValueError: If the config is invalid or incomplete.
    """
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(config_path, "r") as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        raise ValueError(f"Config file must be a YAML mapping, got {type(raw).__name__}")

    sentinel_raw = raw.get("sentinel", {})
    sentinel = SentinelConfig(
        api_url=str(sentinel_raw.get("api_url", "")),
        api_token=str(sentinel_raw.get("api_token", "")),
        server_id=str(sentinel_raw.get("server_id", "")),
        environment=str(sentinel_raw.get("environment", "")),
        scan_interval=parse_duration(sentinel_raw.get("scan_interval", "5m")),
        state_file=str(sentinel_raw.get("state_file", "/var/lib/sentinel/state.json")),
    )

    repos = []
    for r in raw.get("repos", []):
        repos.append(RepoConfig(
            alias=str(r.get("alias", "")),
            path=str(r.get("path", "")),
            branch=str(r.get("branch", "main")),
        ))

    logging_raw = raw.get("logging", {})
    logging_cfg = LoggingConfig(
        level=str(logging_raw.get("level", "INFO")),
        file=str(logging_raw.get("file", "/var/log/sentinel/agent.log")),
        max_bytes=int(logging_raw.get("max_bytes", 10_485_760)),
        backup_count=int(logging_raw.get("backup_count", 5)),
    )

    config = AgentConfig(sentinel=sentinel, repos=repos, logging=logging_cfg)

    errors = config.validate()
    if errors:
        raise ValueError("Configuration errors:\n  - " + "\n  - ".join(errors))

    return config
