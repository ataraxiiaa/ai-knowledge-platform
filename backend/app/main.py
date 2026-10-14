from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import api_router
from app.core.config import settings


app = FastAPI(
    title="AI Knowledge Platform API",
    version="0.1.0",
    description="API for AI Knowledge Platform",
)

# Enable CORS for frontend client communication
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include all API routes
app.include_router(api_router)


@app.get("/", tags=["Root"])
async def root():
    return {"message": "Welcome to AI Knowledge Platform API"}
