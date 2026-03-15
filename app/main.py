from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import api_router
from app.core.config import settings
from app.core.exception_handlers import register_exception_handlers
from app.kafka.manager import get_kafka_manager


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    # Startup
    kafka_manager = get_kafka_manager()
    await kafka_manager.start()
    yield
    # Shutdown
    await kafka_manager.stop()


app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Real-time voice translation video conferencing platform API",
    version=settings.VERSION,
    lifespan=lifespan,
)

# Set all CORS enabled origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)
app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/health", tags=["health"])
async def health_check() -> dict:
    kafka_manager = get_kafka_manager()
    kafka_health = await kafka_manager.health_check()

    return {
        "status": "ok" if kafka_health["status"] == "healthy" else "degraded",
        "version": settings.VERSION,
        "services": {
            "kafka": kafka_health,
        },
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
