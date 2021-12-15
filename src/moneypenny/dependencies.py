"""FastAPI dependencies for Moneypenny."""

from typing import Optional

from fastapi import Depends
from safir.dependencies.logger import logger_dependency
from structlog.stdlib import BoundLogger

from .kubernetes import KubernetesClient
from .moneypenny import Moneypenny


class MoneypennyDependency:
    """Constructs a Moneypenny object that shares a Kubernetes client."""

    def __init__(self) -> None:
        self.k8s_client: Optional[KubernetesClient] = None

    async def __call__(
        self, logger: BoundLogger = Depends(logger_dependency)
    ) -> Moneypenny:
        assert self.k8s_client, "moneypenny_dependency not initialized"
        return Moneypenny(self.k8s_client, logger)

    async def initialize(self) -> None:
        """Initialize the dependency.

        This must be called during application startup.
        """
        self.k8s_client = await KubernetesClient.create()

    async def aclose(self) -> None:
        """Cleanly close resources used by the Moneypenny singleton."""
        if self.k8s_client:
            await self.k8s_client.aclose()
            self.k8s_client = None


moneypenny_dependency = MoneypennyDependency()
"""The dependency that will return the Moneypenny singleton."""
