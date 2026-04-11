"""YAML configuration loader and validation for the Sentinel agent."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class ProjectConfig:
    name: str
    path: str
    client: str
    branch: str = "main"

    def validate(self) -> list[str]:
        errors = []
        if not self.name:
            errors.append("Project name is required")
        if not self.path:
            errors.append(f"Project '{self.name}': path is required")
        elif not Path(self.path).is_absolute():
            errors.append(f"Project '{self.name}': path must be absolute, got '{self.path}'")
        if not self.client:
            errors.append(f"Project '{self.name}': client is required")
        return errors


@dataclass
class SentinelConfig:
    api_url: str
    api_token: str
    server_id: str
    environment: str
    scan_interval: int = 300
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
        if self.scan_interval < 10:
            errors.append(f"sentinel.scan_interval must be >= 10 seconds, got {self.scan_interval}")
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
    projects: list[ProjectConfig] = field(default_factory=list)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    def validate(self) -> list[str]:
        errors = self.sentinel.validate()
        errors.extend(self.logging.validate())
        if not self.projects:
            errors.append("At least one project must be configured")
        for project in self.projects:
            errors.extend(project.validate())
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
        scan_interval=int(sentinel_raw.get("scan_interval", 300)),
        state_file=str(sentinel_raw.get("state_file", "/var/lib/sentinel/state.json")),
    )

    projects = []
    for p in raw.get("projects", []):
        projects.append(ProjectConfig(
            name=str(p.get("name", "")),
            path=str(p.get("path", "")),
            client=str(p.get("client", "")),
            branch=str(p.get("branch", "main")),
        ))

    logging_raw = raw.get("logging", {})
    logging_cfg = LoggingConfig(
        level=str(logging_raw.get("level", "INFO")),
        file=str(logging_raw.get("file", "/var/log/sentinel/agent.log")),
        max_bytes=int(logging_raw.get("max_bytes", 10_485_760)),
        backup_count=int(logging_raw.get("backup_count", 5)),
    )

    config = AgentConfig(sentinel=sentinel, projects=projects, logging=logging_cfg)

    errors = config.validate()
    if errors:
        raise ValueError("Configuration errors:\n  - " + "\n  - ".join(errors))

    return config
