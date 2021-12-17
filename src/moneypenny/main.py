"""The main application factory for the Moneypenny service.

Notes
-----
Be aware that, following the normal pattern for FastAPI services, the app is
constructed when this module is loaded and is not deferred until a function is
called.
"""

from importlib.metadata import metadata

import structlog
from fastapi import FastAPI
from safir.logging import configure_logging
from safir.middleware.x_forwarded import XForwardedMiddleware

from .config import config
from .dependencies import moneypenny_dependency
from .handlers.external import external_router
from .handlers.internal import internal_router

__all__ = ["app", "config"]


configure_logging(
    profile=config.profile,
    log_level=config.log_level,
    name=config.logger_name,
    add_timestamp=True,
)

app = FastAPI()
"""The main FastAPI application for Moneypenny."""

# Define the external routes in a subapp so that it will serve its own OpenAPI
# interface definition and documentation URLs under the external URL.
_subapp = FastAPI(
    title="moneypenny",
    description=metadata("moneypenny").get("Summary", ""),
    version=metadata("moneypenny").get("Version", "0.0.0"),
)
_subapp.include_router(external_router)

# Attach the internal routes and subapp to the main application.
app.include_router(internal_router)
app.mount(f"/{config.name}", _subapp)


@app.on_event("startup")
async def startup_event() -> None:
    logger = structlog.get_logger(config.logger_name)
    app.add_middleware(XForwardedMiddleware)
    await moneypenny_dependency.initialize(logger)


@app.on_event("shutdown")
async def shutdown_event() -> None:
    await moneypenny_dependency.aclose()
