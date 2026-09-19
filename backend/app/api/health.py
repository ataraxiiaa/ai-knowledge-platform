from fastapi import APIRouter

from app.schemas.health import HealthResponse

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=HealthResponse)
async def get_health():
    """Health check endpoint to verify API service status."""
    return HealthResponse(status="healthy")
