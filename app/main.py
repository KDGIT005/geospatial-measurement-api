"""FastAPI application factory.

Creates the app, registers routers and exception handlers, and sets up
the database tables on startup via the lifespan context manager.
"""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.files import router as files_router
from app.core.exceptions import GeoAPIError, geo_api_exception_handler
from app.database import Base, engine
from app.schemas import HealthResponse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Create database tables on startup."""
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created")
    yield


def create_app() -> FastAPI:
    """Build and return the configured FastAPI application."""
    app = FastAPI(
        title="Geospatial File Measurement API",
        description=(
            "Upload geospatial files (KML or zipped Shapefile), "
            "extract features, and compute projected + geodesic measurements."
        ),
        version="1.0.0",
        lifespan=lifespan,
    )

    # Exception handlers
    app.add_exception_handler(GeoAPIError, geo_api_exception_handler)

    # Routers
    app.include_router(files_router, prefix="/api/files", tags=["Files"])

    # Health check
    @app.get("/health", tags=["Health"], response_model=HealthResponse)
    def health_check() -> dict:
        """Returns service health status."""
        return {"status": "ok"}

    # Root redirect to API documentation
    @app.get("/", include_in_schema=False)
    def root():
        """Redirect root URL to interactive documentation."""
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/docs")

    return app


app = create_app()
