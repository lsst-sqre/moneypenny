"""FastAPI dependencies for Moneypenny."""

from fastapi import Depends
from safir.dependencies.logger import logger_dependency
from structlog.stdlib import BoundLogger

from .kubernetes import initialize_kubernetes
from .moneypenny import Moneypenny


class MoneypennyDependency:
    """Constructs a Moneypenny object that shares a Kubernetes client."""

    async def __call__(
        self, logger: BoundLogger = Depends(logger_dependency)
    ) -> Moneypenny:
        return Moneypenny(logger)

    async def initialize(self, logger: BoundLogger) -> None:
        """Initialize the dependency.

        This must be called during application startup.
        """
        await initialize_kubernetes(logger)


moneypenny_dependency = MoneypennyDependency()
"""The dependency that will return the Moneypenny singleton."""
