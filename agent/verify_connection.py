"""Verify the agent can reach the central API (health + authenticated heartbeat).

Run either:

    cd /opt/sentinel && ./venv/bin/python -m agent.verify_connection --config /etc/sentinel/agent.yaml

Or (works without cd; path bootstrap below):

    sudo -u sentinel /opt/sentinel/venv/bin/python /opt/sentinel/agent/verify_connection.py --config /etc/sentinel/agent.yaml

Exit code 0 if both checks pass, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Allow `python /opt/sentinel/agent/verify_connection.py` — package root must be on sys.path
_repo_root = str(Path(__file__).resolve().parent.parent)
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

import requests

from agent.agent import get_version
from agent.config import load_config


def _health_url(api_url: str) -> str:
    base = api_url.rstrip("/")
    return f"{base}/health"


def _heartbeat_url(api_url: str) -> str:
    base = api_url.rstrip("/")
    return f"{base}/heartbeat"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Test connectivity from this machine to the Sentinel central API",
    )
    parser.add_argument(
        "--config",
        default="/etc/sentinel/agent.yaml",
        help="Path to agent YAML (default: /etc/sentinel/agent.yaml)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=15.0,
        help="HTTP timeout in seconds (default: 15)",
    )
    args = parser.parse_args()

    try:
        cfg = load_config(args.config)
    except (FileNotFoundError, ValueError) as e:
        print(f"Config error: {e}", file=sys.stderr)
        sys.exit(1)

    api_url = cfg.sentinel.api_url.rstrip("/")
    token = cfg.sentinel.api_token
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    print(f"Central API base: {api_url}")
    print(f"Agent version:    {get_version()}")
    print()

    # 1) Public health (no auth) — proves DNS/TLS/proxy reach the API process
    health = _health_url(api_url)
    print(f"1. GET  {health}")
    try:
        r = requests.get(health, timeout=args.timeout)
        if r.status_code != 200:
            print(f"   FAIL  HTTP {r.status_code}: {r.text[:200]}", file=sys.stderr)
            sys.exit(1)
        body: Any
        try:
            body = r.json()
        except json.JSONDecodeError:
            print("   FAIL  Response is not JSON", file=sys.stderr)
            sys.exit(1)
        print(f"   OK    {body}")
    except requests.RequestException as e:
        print(f"   FAIL  {e}", file=sys.stderr)
        sys.exit(1)

    # 2) Authenticated heartbeat — proves token + routing + DB on central
    hb_url = _heartbeat_url(api_url)
    payload = {
        "server_id": cfg.sentinel.server_id,
        "environment": cfg.sentinel.environment,
        "projects_watched": [p.name for p in cfg.projects],
        "agent_version": get_version(),
    }
    print()
    print(f"2. POST {hb_url}")
    try:
        r = requests.post(hb_url, json=payload, headers=headers, timeout=args.timeout)
        if r.status_code != 200:
            print(
                f"   FAIL  HTTP {r.status_code}: {r.text[:500]}",
                file=sys.stderr,
            )
            if r.status_code == 401:
                print(
                    "   Hint: invalid or revoked API token — run "
                    "`python api/manage.py create-token` on central and update agent.yaml.",
                    file=sys.stderr,
                )
            sys.exit(1)
        try:
            body = r.json()
        except json.JSONDecodeError:
            print("   FAIL  Response is not JSON", file=sys.stderr)
            sys.exit(1)
        print(f"   OK    {body}")
    except requests.RequestException as e:
        print(f"   FAIL  {e}", file=sys.stderr)
        sys.exit(1)

    print()
    print("Central server is reachable and accepted this agent's token.")
    print("On central, check: GET /api/v1/servers (admin token) to see last_seen.")


if __name__ == "__main__":
    main()
