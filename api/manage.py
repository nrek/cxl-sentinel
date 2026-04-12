"""CLI management tool for the Sentinel API.

Commands:
    init-db       Create all database tables
    create-token  Generate a new API token
    list-tokens   Show all registered tokens
    revoke-token  Deactivate a token by name
    test-email    Dry-run or send a sample deploy notification HTML email
"""

import argparse
import os
import sys
from pathlib import Path

# Allow running as `python api/manage.py` from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.auth import generate_token, hash_token
from api.config import load_api_config
from api.database import init_engine, get_engine, get_session
from api.models import ApiToken, Base
from api.notifications import sendgrid_provider, smtp_provider
from api.notifications.renderer import render_deploy_email


def _get_config_path() -> str:
    return os.environ.get("SENTINEL_CONFIG", "api/config.yaml")


def _init_db(engine):
    Base.metadata.create_all(bind=engine)


def cmd_init_db(args):
    config = load_api_config(_get_config_path())
    init_engine(config.database_url)
    engine = get_engine()
    _init_db(engine)
    print(f"Database initialized: {config.database_url}")

    if config.tokens:
        session_gen = get_session()
        session = next(session_gen)
        try:
            seeded = 0
            for entry in config.tokens:
                existing = session.query(ApiToken).filter(ApiToken.name == entry.name).first()
                if existing:
                    continue
                token_record = ApiToken(
                    name=entry.name,
                    token_hash=hash_token(entry.token),
                    role="admin" if entry.name == "admin" else "agent",
                    is_active=True,
                )
                session.add(token_record)
                seeded += 1
            session.commit()
            if seeded:
                print(f"Seeded {seeded} token(s) from config file")
        finally:
            session.close()


def cmd_create_token(args):
    config = load_api_config(_get_config_path())
    init_engine(config.database_url)
    engine = get_engine()
    _init_db(engine)

    session_gen = get_session()
    session = next(session_gen)
    try:
        existing = session.query(ApiToken).filter(ApiToken.name == args.name).first()
        if existing:
            print(f"Error: Token with name '{args.name}' already exists", file=sys.stderr)
            sys.exit(1)

        plaintext = generate_token()
        record = ApiToken(
            name=args.name,
            token_hash=hash_token(plaintext),
            role=args.role,
            is_active=True,
        )
        session.add(record)
        session.commit()

        print(f"Token created for '{args.name}' (role: {args.role})")
        print(f"Token: {plaintext}")
        print("Store this token securely -- it cannot be retrieved again.")
    finally:
        session.close()


def cmd_list_tokens(args):
    config = load_api_config(_get_config_path())
    init_engine(config.database_url)

    session_gen = get_session()
    session = next(session_gen)
    try:
        tokens = session.query(ApiToken).order_by(ApiToken.created_at).all()
        if not tokens:
            print("No tokens found")
            return

        print(f"{'Name':<24} {'Role':<12} {'Active':<8} {'Created'}")
        print("-" * 72)
        for t in tokens:
            active_str = "yes" if t.is_active else "NO"
            created = t.created_at.strftime("%Y-%m-%d %H:%M") if t.created_at else "unknown"
            print(f"{t.name:<24} {t.role:<12} {active_str:<8} {created}")
    finally:
        session.close()


def cmd_revoke_token(args):
    config = load_api_config(_get_config_path())
    init_engine(config.database_url)

    session_gen = get_session()
    session = next(session_gen)
    try:
        record = session.query(ApiToken).filter(ApiToken.name == args.name).first()
        if not record:
            print(f"Error: No token found with name '{args.name}'", file=sys.stderr)
            sys.exit(1)

        record.is_active = False
        session.commit()
        print(f"Token '{args.name}' has been revoked")
    finally:
        session.close()


def cmd_test_email(args):
    """Render a sample deploy email; optionally send to one address."""
    config = load_api_config(_get_config_path())
    n = config.notifications

    commit_hash = "a" * 40
    subject, html_body = render_deploy_email(
        project=args.project,
        client=args.client,
        server_id=args.server,
        environment=args.environment,
        commit_hash=commit_hash,
        commit_message=args.message,
        commit_author=args.author,
        files_changed=args.files,
        commit_count=args.commits,
        contributors=(
            [e.strip() for e in args.contributor.split(",") if e.strip()]
            if args.contributor
            else ["dev@example.com"]
        ),
        branch=args.branch,
        detected_at=args.detected_at,
        previous_commit_hash=None,
        branding=n.branding,
    )

    if args.dry_run:
        print(subject)
        print("-" * 72)
        print(html_body)
        print("-" * 72, file=sys.stderr)
        print("Dry-run: no email sent. Omit --dry-run and use --to you@example.com to send.", file=sys.stderr)
        return

    if not args.to:
        print(
            "Specify --to you@example.com to send, or --dry-run to print HTML only.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not n.smtp.enabled and not n.sendgrid.enabled:
        print(
            "Enable notifications.smtp or notifications.sendgrid in config to send email.",
            file=sys.stderr,
        )
        sys.exit(1)

    recipients = [args.to.strip()]
    if n.sendgrid.enabled:
        ok = sendgrid_provider.send_email(n.sendgrid, recipients, subject, html_body)
    else:
        ok = smtp_provider.send_email(n.smtp, recipients, subject, html_body)

    if ok:
        print(f"Test email sent to {args.to}")
    else:
        print("Send failed — check API logs and SMTP/SendGrid settings.", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="CXL Sentinel API Management")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-db", help="Initialize the database schema")

    create_parser = subparsers.add_parser("create-token", help="Generate a new API token")
    create_parser.add_argument("--name", required=True, help="Unique name for the token (e.g., server hostname)")
    create_parser.add_argument("--role", choices=["agent", "admin", "readonly"], default="agent", help="Token role")

    subparsers.add_parser("list-tokens", help="List all registered tokens")

    revoke_parser = subparsers.add_parser("revoke-token", help="Revoke (deactivate) a token")
    revoke_parser.add_argument("--name", required=True, help="Name of the token to revoke")

    test_parser = subparsers.add_parser(
        "test-email",
        help="Render sample deploy notification email; --dry-run prints HTML, --to sends one message",
    )
    test_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print subject + HTML to stdout; do not send mail",
    )
    test_parser.add_argument(
        "--to",
        metavar="EMAIL",
        help="Send test email only to this address (uses active SMTP or SendGrid)",
    )
    test_parser.add_argument("--project", default="my-web-app", help="Sample project name")
    test_parser.add_argument("--client", default="acme-corp", help="Sample client id")
    test_parser.add_argument("--server", default="prod-web-01", help="Sample server_id")
    test_parser.add_argument(
        "--environment",
        choices=["production", "staging"],
        default="staging",
        help="Sample environment",
    )
    test_parser.add_argument("--message", default="Sample deploy — notification test", help="Sample commit message")
    test_parser.add_argument("--author", default="dev@example.com", help="Sample commit author")
    test_parser.add_argument("--files", type=int, default=12, help="Sample files_changed count")
    test_parser.add_argument("--commits", type=int, default=3, help="Sample commit_count")
    test_parser.add_argument(
        "--contributor",
        default="",
        help="Comma-separated contributor emails (default: dev@example.com)",
    )
    test_parser.add_argument("--branch", default="main", help="Sample branch name")
    test_parser.add_argument(
        "--detected-at",
        default="2026-04-12 18:00:00 UTC",
        dest="detected_at",
        help="Sample detected_at line",
    )

    args = parser.parse_args()

    commands = {
        "init-db": cmd_init_db,
        "create-token": cmd_create_token,
        "list-tokens": cmd_list_tokens,
        "revoke-token": cmd_revoke_token,
        "test-email": cmd_test_email,
    }

    try:
        commands[args.command](args)
    except (FileNotFoundError, ValueError) as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
