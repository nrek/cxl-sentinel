#!/usr/bin/env python3
"""Migrate api/config.yaml from the old project-based format to server_id-based rules.

Usage (on the Central server):
    python api/migrate_config.py api/config.yaml

Reads the existing config, converts notification rules from the old format
(project/client based) to the new format (server_id/environments/send_schedule),
strips comments, and writes a clean config. The original file is backed up
as config.yaml.bak before overwriting.
"""

import shutil
import sys
from pathlib import Path

import yaml


def migrate(path: str) -> None:
    p = Path(path)
    if not p.exists():
        print(f"File not found: {path}", file=sys.stderr)
        sys.exit(1)

    with open(p) as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        print(f"Invalid YAML structure in {path}", file=sys.stderr)
        sys.exit(1)

    # --- sentinel section (keep as-is, just ensure keys exist) ---
    sentinel = raw.get("sentinel", {})

    # --- auth section (keep as-is) ---
    auth = raw.get("auth", {})

    # --- notifications ---
    notif = raw.get("notifications", {})

    smtp = notif.get("smtp", {})
    sendgrid = notif.get("sendgrid", {})
    branding = notif.get("branding", {})

    # Migrate rules from old format to new
    old_rules = notif.get("rules", [])
    new_rules = _migrate_rules(old_rules)

    # Build clean config
    clean = {
        "sentinel": {
            "database_url": sentinel.get("database_url", "sqlite:///sentinel.db"),
            "host": sentinel.get("host", "0.0.0.0"),
            "port": sentinel.get("port", 8400),
            "log_level": sentinel.get("log_level", "INFO"),
            "log_file": sentinel.get("log_file", "/var/log/sentinel/api.log"),
        },
        "auth": {
            "tokens": auth.get("tokens", []),
        },
        "notifications": {
            "smtp": _clean_smtp(smtp),
            "sendgrid": _clean_sendgrid(sendgrid),
            "branding": _clean_branding(branding),
            "rules": new_rules,
        },
    }

    # Backup original
    backup = p.with_suffix(".yaml.bak")
    shutil.copy2(p, backup)
    print(f"Backed up original to {backup}")

    with open(p, "w") as f:
        yaml.dump(clean, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    print(f"Migrated config written to {p}")
    print(f"  {len(new_rules)} notification rule(s)")


def _migrate_rules(old_rules: list) -> list:
    """Convert old-format rules to new server_id-based rules."""
    if not old_rules:
        return []

    new_rules = []
    for r in old_rules:
        rule = {}

        # Old format used "project" — map to server_id
        if "server_id" in r:
            rule["server_id"] = r["server_id"]
        elif "project" in r:
            rule["server_id"] = r["project"]
        else:
            rule["server_id"] = "*"

        # server_alias (new field, or fall back to old "client")
        if "server_alias" in r:
            rule["server_alias"] = r["server_alias"]
        elif "client" in r:
            rule["server_alias"] = r["client"]
        else:
            rule["server_alias"] = ""

        # environments
        if "environments" in r:
            rule["environments"] = r["environments"]
        elif "environment" in r:
            env = r["environment"]
            rule["environments"] = [env] if isinstance(env, str) else env
        else:
            rule["environments"] = ["production", "staging"]

        # send_schedule (new field)
        rule["send_schedule"] = r.get("send_schedule", "6h")

        # recipients
        rule["recipients"] = r.get("recipients", [])

        new_rules.append(rule)

    return new_rules


def _clean_smtp(raw: dict) -> dict:
    if not raw:
        return {"enabled": False}
    return {
        "enabled": bool(raw.get("enabled", False)),
        "host": raw.get("host", "smtp.gmail.com"),
        "port": int(raw.get("port", 587)),
        "use_tls": bool(raw.get("use_tls", True)),
        "username": raw.get("username", ""),
        "password": raw.get("password", ""),
        "from_address": raw.get("from_address", ""),
        "from_name": raw.get("from_name", "CXL Sentinel"),
    }


def _clean_sendgrid(raw: dict) -> dict:
    if not raw:
        return {"enabled": False}
    return {
        "enabled": bool(raw.get("enabled", False)),
        "api_key": raw.get("api_key", ""),
        "from_address": raw.get("from_address", ""),
        "from_name": raw.get("from_name", "CXL Sentinel"),
    }


def _clean_branding(raw: dict) -> dict:
    if not raw:
        return {}
    return {
        "logo_url": raw.get("logo_url", ""),
        "accent_color": raw.get("accent_color", "#2563eb"),
        "header_theme": raw.get("header_theme", "dark"),
        "header_background": raw.get("header_background", ""),
        "company_name": raw.get("company_name", ""),
        "footer_text": raw.get("footer_text", ""),
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} <path-to-config.yaml>")
        sys.exit(1)
    migrate(sys.argv[1])
