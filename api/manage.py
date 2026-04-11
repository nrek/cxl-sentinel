"""CLI management tool for the Sentinel API.

Commands:
    init-db       Create all database tables
    create-token  Generate a new API token
    list-tokens   Show all registered tokens
    revoke-token  Deactivate a token by name
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

    args = parser.parse_args()

    commands = {
        "init-db": cmd_init_db,
        "create-token": cmd_create_token,
        "list-tokens": cmd_list_tokens,
        "revoke-token": cmd_revoke_token,
    }

    try:
        commands[args.command](args)
    except (FileNotFoundError, ValueError) as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
