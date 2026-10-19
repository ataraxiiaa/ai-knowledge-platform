from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import api_router
from app.core.config import settings
from app.services import observability


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if not settings.WEB_LOCAL_JOBS:
        yield
        return
    from app.services.web_local_jobs import start
    stop, thread = start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=5)


app = FastAPI(
    title="AI Knowledge Platform API",
    version="0.1.0",
    description="API for AI Knowledge Platform",
    lifespan=lifespan,
)
observability.initialize("ai-knowledge-api")


@app.middleware("http")
async def observe_http(request, call_next):
    from time import perf_counter

    started = perf_counter()
    status = 500
    route = "unmatched"
    with observability.span("http.server.request", {"http.request.method": request.method}) as current:
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            matched = request.scope.get("route")
            if matched is not None:
                route = getattr(matched, "path", "unmatched")
            if current is not None:
                current.set_attribute("http.route", route)
                current.set_attribute("http.response.status_code", status)
            observability.record_http(request.method, route, status, perf_counter() - started)

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
