from fastapi import FastAPI

from app.api import api_router

app = FastAPI(
    title="AI Knowledge Platform API",
    version="0.1.0",
    description="API for AI Knowledge Platform",
)

# Include all API routes
app.include_router(api_router)


@app.get("/", tags=["Root"])
async def root():
    return {"message": "Welcome to AI Knowledge Platform API"}
