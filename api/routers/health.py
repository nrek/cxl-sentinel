"""Health check endpoint -- no authentication required."""

from pathlib import Path

from fastapi import APIRouter

from api.schemas import HealthResponse

router = APIRouter()

_VERSION_FILE = Path(__file__).resolve().parent.parent.parent / "VERSION"


def _get_version() -> str:
    try:
        return _VERSION_FILE.read_text().strip()
    except OSError:
        return "unknown"


@router.get("/health", response_model=HealthResponse)
async def health_check():
    return HealthResponse(status="healthy", version=_get_version())
