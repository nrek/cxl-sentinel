"""Pydantic request/response schemas for the Sentinel API."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class DeployEventCreate(BaseModel):
    server_id: str = Field(..., min_length=1, max_length=128)
    environment: str = Field(..., pattern=r"^(production|staging)$")
    repo_alias: str = Field(..., min_length=1, max_length=128)
    commit_hash: str = Field(..., min_length=7, max_length=64)
    commit_message: Optional[str] = Field(None, max_length=1000)
    commit_author: Optional[str] = Field(None, max_length=256)
    commit_timestamp: Optional[datetime] = None
    previous_commit_hash: Optional[str] = Field(None, max_length=64)
    files_changed: int = Field(0, ge=0)
    commit_count: int = Field(1, ge=1)
    contributors: list[str] = Field(default_factory=list)
    branch: str = Field("main", max_length=128)
    detected_at: datetime


class DeployEventResponse(BaseModel):
    id: int
    status: str = "recorded"

    model_config = {"from_attributes": True}


class DeployEventDetail(BaseModel):
    id: int
    server_id: str
    environment: str
    repo_alias: str
    branch: str
    commit_hash: str
    commit_message: Optional[str]
    commit_author: Optional[str]
    commit_timestamp: Optional[datetime]
    previous_commit_hash: Optional[str]
    files_changed: int
    commit_count: int
    contributors: Optional[list[str]]
    detected_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


class HeartbeatCreate(BaseModel):
    server_id: str = Field(..., min_length=1, max_length=128)
    environment: str = Field(..., pattern=r"^(production|staging)$")
    repos_watched: list[str] = Field(default_factory=list)
    agent_version: Optional[str] = Field(None, max_length=32)


class HeartbeatResponse(BaseModel):
    status: str = "ok"
    server_time: datetime


class ServerDetail(BaseModel):
    server_id: str
    environment: str
    repos_watched: Optional[list[str]]
    agent_version: Optional[str]
    last_seen: datetime
    is_alive: bool

    model_config = {"from_attributes": True}


class HealthResponse(BaseModel):
    status: str = "healthy"
    version: str


class ErrorResponse(BaseModel):
    detail: str
