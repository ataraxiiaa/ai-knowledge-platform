"""Owner-scoped, current-UTC-day cache measurements."""
from fastapi import APIRouter, Depends

from app.api.documents import owned_workspace
from app.models.workspaces import Workspace
from app.services import cache

router = APIRouter(prefix="/workspaces", tags=["Cache"])


@router.get("/{id}/cache-metrics")
def get_cache_metrics(workspace: Workspace = Depends(owned_workspace)) -> dict:
    return cache.metrics(workspace.id)
