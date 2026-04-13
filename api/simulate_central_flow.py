#!/usr/bin/env python3
"""End-to-end flow simulation for the Sentinel *central* host.

Uses the real SQLite database, optional live HTTP queries against the API, and the
same HTML render + SMTP/SendGrid path as production — but sends mail only to a
single test address you choose (no production recipient lists).

Typical use (on the API server, as the same user that owns the DB):

  export SENTINEL_CONFIG=/var/www/cxl-sentinel/api/config.yaml
  sudo -u www-data env SENTINEL_CONFIG=... .venv/bin/python api/simulate_central_flow.py \\
    --to you@example.com

Optional HTTP checks (same data you would see from curl):

  python api/simulate_central_flow.py --to you@example.com \\
    --api-url https://sentinel.example.com/api/v1 \\
    --token sk-admin-xxxxxxxx

  --dry-run     Print steps and rendered subjects; do not send email
  --no-http     Skip GET /health /events /servers
  --no-email    Only DB (+ HTTP if configured); no mail
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests
from sqlalchemy.exc import OperationalError

from api.config import load_api_config
from api.database import init_engine, get_session
from api.models import DeployEvent, ServerHeartbeat
from api.notifications import sendgrid_provider, smtp_provider
from api.notifications.renderer import render_deploy_email

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("sentinel.simulate")


def _config_path() -> str:
    return os.environ.get("SENTINEL_CONFIG", "api/config.yaml")


def _contributors_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return [str(x) for x in data] if isinstance(data, list) else []
    except json.JSONDecodeError:
        log.warning("Could not parse contributors JSON; using empty list")
        return []


def _detected_at_str(ev: DeployEvent) -> str:
    if ev.detected_at is None:
        return ""
    return ev.detected_at.strftime("%Y-%m-%d %H:%M:%S UTC")


def _print_header(title: str) -> None:
    print()
    print(f"=== {title} ===")


def step_database(session, limit: int, event_id: int | None) -> list[DeployEvent]:
    _print_header("Database (live)")
    try:
        n_events = session.query(DeployEvent).count()
        n_heartbeats = session.query(ServerHeartbeat).count()
    except OperationalError as e:
        print(f"Database query failed: {e}")
        print("Hint: run `python api/manage.py init-db` with the same SENTINEL_CONFIG, or fix database_url.")
        raise SystemExit(1) from e
    print(f"deploy_events rows: {n_events}")
    print(f"server_heartbeats rows: {n_heartbeats}")

    q = session.query(DeployEvent).order_by(DeployEvent.detected_at.desc())
    if event_id is not None:
        ev = session.query(DeployEvent).filter(DeployEvent.id == event_id).first()
        rows = [ev] if ev else []
        if not rows:
            print(f"No deploy_events row with id={event_id}")
    else:
        rows = q.limit(limit).all()

    if not rows:
        print("No deploy events to list.")
        return []

    print()
    print(f"{'id':>6}  {'detected_at':<22}  {'server_id':<18}  {'repo_alias':<20}  commit")
    print("-" * 100)
    for ev in rows:
        if ev is None:
            continue
        short = (ev.commit_hash or "")[:12]
        det = ev.detected_at.isoformat() if ev.detected_at else ""
        print(f"{ev.id:>6}  {det:<22}  {ev.server_id:<18}  {ev.repo_alias:<20}  {short}")
    return [e for e in rows if e is not None]


def step_http(api_url: str, token: str, verify_tls: bool) -> None:
    _print_header("HTTP API (live)")
    base = api_url.rstrip("/")
    try:
        r = requests.get(f"{base}/health", timeout=15, verify=verify_tls)
        print(f"GET {base}/health -> {r.status_code} {r.text[:200]}")
    except requests.RequestException as e:
        print(f"GET /health failed: {e}")

    h = {"Authorization": f"Bearer {token}"}
    for path, label in (("/events?limit=10", "events"), ("/servers", "servers")):
        try:
            r = requests.get(f"{base}{path}", headers=h, timeout=15, verify=verify_tls)
            snippet = r.text[:500] + ("..." if len(r.text) > 500 else "")
            print(f"GET {base}{path} -> {r.status_code}")
            print(snippet)
        except requests.RequestException as e:
            print(f"GET {path} failed: {e}")


def step_email_replay(
    notifications,
    events: list[DeployEvent],
    to: str,
    dry_run: bool,
) -> None:
    _print_header("Email replay (production renderer + provider; recipients overridden)")
    n = notifications
    if not n.smtp.enabled and not n.sendgrid.enabled:
        print("No email provider enabled (smtp / sendgrid). Skipping send.")
        return

    recipients = [to.strip()]
    provider = "sendgrid" if n.sendgrid.enabled else "smtp"

    for ev in events:
        contributors = _contributors_list(ev.contributors)
        if not contributors and ev.commit_author:
            contributors = [ev.commit_author]

        subject, html_body = render_deploy_email(
            repo_alias=ev.repo_alias,
            server_id=ev.server_id,
            environment=ev.environment,
            commit_hash=ev.commit_hash,
            commit_message=ev.commit_message or "",
            commit_author=ev.commit_author or "",
            files_changed=ev.files_changed or 0,
            commit_count=ev.commit_count or 1,
            contributors=contributors,
            branch=ev.branch or "main",
            detected_at=_detected_at_str(ev),
            previous_commit_hash=ev.previous_commit_hash,
            branding=n.branding,
        )

        print()
        print(f"--- event id={ev.id} -> test recipient only ---")
        print(f"subject: {subject}")
        if dry_run:
            print(f"[dry-run] would send via {provider} to {recipients}")
            print(f"[dry-run] HTML length: {len(html_body)} bytes")
            continue

        if n.sendgrid.enabled:
            ok = sendgrid_provider.send_email(n.sendgrid, recipients, subject, html_body)
        else:
            ok = smtp_provider.send_email(n.smtp, recipients, subject, html_body)

        print(f"send: {'OK' if ok else 'FAILED'} ({provider} -> {recipients[0]})")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Simulate central flow: live DB (+ optional HTTP) + test-only email replay",
    )
    parser.add_argument(
        "--to",
        metavar="EMAIL",
        help="Sole recipient for replayed deploy emails (required unless --no-email)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=3,
        help="Latest N deploy events to replay (default: 3)",
    )
    parser.add_argument("--event-id", type=int, help="Replay only this deploy_events.id")
    parser.add_argument(
        "--api-url",
        help="Base API URL including /api/v1, e.g. https://host/api/v1",
    )
    parser.add_argument("--token", help="Bearer token for --api-url (admin or readonly)")
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Disable TLS verify for --api-url (dev only)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not send email; print subject and provider info",
    )
    parser.add_argument("--no-http", action="store_true", help="Skip HTTP GET checks")
    parser.add_argument("--no-email", action="store_true", help="Skip email replay")

    args = parser.parse_args()

    if not args.no_email and not args.to:
        parser.error("--to is required unless --no-email")

    config = load_api_config(_config_path())
    init_engine(config.database_url)
    session_gen = get_session()
    session = next(session_gen)
    try:
        events = step_database(session, args.limit, args.event_id)

        if not args.no_http and args.api_url and args.token:
            step_http(args.api_url, args.token, verify_tls=not args.insecure)
        elif not args.no_http and (args.api_url or args.token):
            print()
            print("Skipping HTTP: provide both --api-url and --token, or use --no-http")

        if not args.no_email and events:
            step_email_replay(
                config.notifications,
                events,
                args.to,
                dry_run=args.dry_run,
            )
        elif not args.no_email and not events:
            print()
            print("No events selected; email step skipped.")

        _print_header("Done")
        print("Review logs above. Check inbox for replay messages (if not --dry-run).")
    finally:
        session.close()
        session_gen.close()


if __name__ == "__main__":
    main()
