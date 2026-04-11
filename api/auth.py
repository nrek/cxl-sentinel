"""Bearer token authentication for the Sentinel API."""

import hashlib
import logging
import secrets
from typing import Optional

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from api.database import get_session
from api.models import ApiToken

logger = logging.getLogger("sentinel.auth")

_bearer_scheme = HTTPBearer()


def hash_token(token: str) -> str:
    """SHA-256 hash a plaintext token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_token() -> str:
    """Generate a cryptographically secure API token."""
    return f"sk-{secrets.token_urlsafe(32)}"


def _get_token_record(
    credentials: HTTPAuthorizationCredentials = Security(_bearer_scheme),
    session: Session = Depends(get_session),
) -> ApiToken:
    """Validate the bearer token and return the token record."""
    token_hash = hash_token(credentials.credentials)

    record = session.query(ApiToken).filter(
        ApiToken.token_hash == token_hash,
        ApiToken.is_active.is_(True),
    ).first()

    if record is None:
        logger.warning("Authentication failed for token hash %s...", token_hash[:16])
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or inactive API token",
        )

    return record


def require_role(*allowed_roles: str):
    """Dependency that enforces role-based access.

    Usage:
        @router.post("/events", dependencies=[Depends(require_role("agent", "admin"))])
    """
    def _check(token: ApiToken = Depends(_get_token_record)):
        if token.role not in allowed_roles:
            logger.warning(
                "Access denied for token '%s' (role=%s), required one of %s",
                token.name, token.role, allowed_roles,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{token.role}' does not have access to this resource",
            )
        return token
    return _check
