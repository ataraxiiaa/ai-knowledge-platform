from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.health import HealthResponse

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=HealthResponse)
async def get_health():
    """Health check endpoint to verify API service status."""
    return HealthResponse(status="healthy")


@router.get("/ready", response_model=HealthResponse)
def get_readiness(db: Session = Depends(get_db)):
    """Check database connectivity and the application schema."""
    try:
        db.execute(text("SELECT id FROM users LIMIT 0"))
        db.execute(text("SELECT id FROM workspaces LIMIT 0"))
        db.execute(text("SELECT id FROM documents LIMIT 0"))
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="Database is not ready") from None
    return HealthResponse(status="healthy")
