from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import api_router
from app.db.session import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize DB tables on application startup
    init_db()
    yield


app = FastAPI(
    title="AI Knowledge Platform API",
    version="0.1.0",
    description="API for AI Knowledge Platform",
    lifespan=lifespan,
)

# Include all API routes
app.include_router(api_router)


@app.get("/", tags=["Root"])
async def root():
    return {"message": "Welcome to AI Knowledge Platform API"}
