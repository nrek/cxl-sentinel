"""SQLAlchemy ORM models for CXL Sentinel."""

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, Column, DateTime, Integer, String, Text, UniqueConstraint, Index, CheckConstraint,
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()


def _utcnow():
    return datetime.now(timezone.utc)


class DeployEvent(Base):
    __tablename__ = "deploy_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    server_id = Column(String(128), nullable=False)
    environment = Column(String(32), nullable=False)
    project = Column(String(128), nullable=False)
    client = Column(String(128), nullable=False)
    branch = Column(String(128), nullable=False, default="main")
    commit_hash = Column(String(64), nullable=False)
    commit_message = Column(Text, nullable=True)
    commit_author = Column(String(256), nullable=True)
    commit_timestamp = Column(DateTime(timezone=True), nullable=True)
    previous_commit_hash = Column(String(64), nullable=True)
    files_changed = Column(Integer, default=0)
    commit_count = Column(Integer, default=1)
    contributors = Column(Text, nullable=True)  # JSON array of unique author emails
    detected_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        UniqueConstraint("server_id", "project", "commit_hash", name="uq_server_project_commit"),
        CheckConstraint("environment IN ('production', 'staging')", name="ck_environment"),
        Index("idx_events_server", "server_id"),
        Index("idx_events_project", "project"),
        Index("idx_events_client", "client"),
        Index("idx_events_env", "environment"),
        Index("idx_events_detected", "detected_at"),
    )


class ServerHeartbeat(Base):
    __tablename__ = "server_heartbeats"

    id = Column(Integer, primary_key=True, autoincrement=True)
    server_id = Column(String(128), nullable=False, unique=True)
    environment = Column(String(32), nullable=False)
    projects_watched = Column(Text, nullable=True)  # JSON array
    agent_version = Column(String(32), nullable=True)
    last_seen = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)


class ApiToken(Base):
    __tablename__ = "api_tokens"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False, unique=True)
    token_hash = Column(String(128), nullable=False, unique=True)
    role = Column(String(32), nullable=False, default="agent")
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        CheckConstraint("role IN ('agent', 'admin', 'readonly')", name="ck_role"),
    )
