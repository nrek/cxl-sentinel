"""API configuration loader."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class TokenEntry:
    name: str
    token: str


@dataclass
class SmtpConfig:
    enabled: bool = False
    host: str = "smtp.gmail.com"
    port: int = 587
    use_tls: bool = True
    username: str = ""
    password: str = ""
    from_address: str = ""
    from_name: str = "CXL Sentinel"


@dataclass
class SendGridConfig:
    enabled: bool = False
    api_key: str = ""
    from_address: str = ""
    from_name: str = "CXL Sentinel"


@dataclass
class BrandingConfig:
    logo_url: str = ""
    accent_color: str = "#2563eb"  # body stats + callout border; not the header strip
    header_theme: str = "dark"  # "dark" = light text on header; "light" = dark text on header
    header_background: str = ""  # header strip color; empty falls back to accent_color
    company_name: str = ""
    footer_text: str = ""


@dataclass
class ProjectNotificationRule:
    """Maps a project (or wildcard '*') to a list of recipient emails."""
    project: str = "*"
    client: str = "*"
    recipients: list[str] = field(default_factory=list)
    environments: list[str] = field(default_factory=lambda: ["production", "staging"])


@dataclass
class NotificationsConfig:
    smtp: SmtpConfig = field(default_factory=SmtpConfig)
    sendgrid: SendGridConfig = field(default_factory=SendGridConfig)
    branding: BrandingConfig = field(default_factory=BrandingConfig)
    rules: list[ProjectNotificationRule] = field(default_factory=list)


@dataclass
class ApiConfig:
    database_url: str = "sqlite:///sentinel.db"
    host: str = "0.0.0.0"
    port: int = 8400
    log_level: str = "INFO"
    log_file: str = "/var/log/sentinel/api.log"
    tokens: list[TokenEntry] = field(default_factory=list)
    notifications: NotificationsConfig = field(default_factory=NotificationsConfig)


def load_api_config(path: str) -> ApiConfig:
    """Load API config from a YAML file.

    Raises:
        FileNotFoundError: If the config file does not exist.
        ValueError: If the config is malformed.
    """
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(config_path, "r") as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        raise ValueError(f"Config must be a YAML mapping, got {type(raw).__name__}")

    sentinel = raw.get("sentinel", {})
    auth = raw.get("auth", {})
    notif_raw = raw.get("notifications", {})

    tokens = []
    for t in auth.get("tokens", []):
        tokens.append(TokenEntry(
            name=str(t.get("name", "")),
            token=str(t.get("token", "")),
        ))

    notifications = _parse_notifications(notif_raw)

    return ApiConfig(
        database_url=str(sentinel.get("database_url", "sqlite:///sentinel.db")),
        host=str(sentinel.get("host", "0.0.0.0")),
        port=int(sentinel.get("port", 8400)),
        log_level=str(sentinel.get("log_level", "INFO")),
        log_file=str(sentinel.get("log_file", "/var/log/sentinel/api.log")),
        tokens=tokens,
        notifications=notifications,
    )


def _parse_notifications(raw: dict) -> NotificationsConfig:
    if not raw:
        return NotificationsConfig()

    smtp_raw = raw.get("smtp", {})
    smtp = SmtpConfig(
        enabled=bool(smtp_raw.get("enabled", False)),
        host=str(smtp_raw.get("host", "smtp.gmail.com")),
        port=int(smtp_raw.get("port", 587)),
        use_tls=bool(smtp_raw.get("use_tls", True)),
        username=str(smtp_raw.get("username", "")),
        password=str(smtp_raw.get("password", "")),
        from_address=str(smtp_raw.get("from_address", "")),
        from_name=str(smtp_raw.get("from_name", "CXL Sentinel")),
    )

    sg_raw = raw.get("sendgrid", {})
    sendgrid = SendGridConfig(
        enabled=bool(sg_raw.get("enabled", False)),
        api_key=str(sg_raw.get("api_key", "")),
        from_address=str(sg_raw.get("from_address", "")),
        from_name=str(sg_raw.get("from_name", "CXL Sentinel")),
    )

    branding_raw = raw.get("branding", {})
    ht = str(branding_raw.get("header_theme", "dark")).strip().lower()
    if ht not in ("dark", "light"):
        ht = "dark"

    branding = BrandingConfig(
        logo_url=str(branding_raw.get("logo_url", "")),
        accent_color=str(branding_raw.get("accent_color", "#2563eb")),
        header_theme=ht,
        header_background=str(branding_raw.get("header_background", "") or ""),
        company_name=str(branding_raw.get("company_name", "")),
        footer_text=str(branding_raw.get("footer_text", "")),
    )

    rules = []
    for r in raw.get("rules", []):
        rules.append(ProjectNotificationRule(
            project=str(r.get("project", "*")),
            client=str(r.get("client", "*")),
            recipients=[str(e) for e in r.get("recipients", [])],
            environments=[str(e) for e in r.get("environments", ["production", "staging"])],
        ))

    return NotificationsConfig(
        smtp=smtp, sendgrid=sendgrid, branding=branding, rules=rules,
    )
