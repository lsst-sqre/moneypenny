"""FastAPI dependencies for Moneypenny."""

from typing import Optional

from fastapi import Depends
from kubernetes_asyncio.client import ApiClient
from safir.dependencies.logger import logger_dependency
from structlog.stdlib import BoundLogger

from .kubernetes import KubernetesClient, initialize_kubernetes
from .moneypenny import Moneypenny


class MoneypennyDependency:
    """Constructs a Moneypenny object that shares a Kubernetes client."""

    def __init__(self) -> None:
        self._api_client: Optional[ApiClient] = None

    async def __call__(
        self, logger: BoundLogger = Depends(logger_dependency)
    ) -> Moneypenny:
        assert self._api_client, "moneypenny_dependency is not initialized"
        k8s_client = KubernetesClient(self._api_client, logger)
        return Moneypenny(k8s_client, logger)

    async def initialize(self, logger: BoundLogger) -> None:
        """Initialize the dependency.

        This must be called during application startup.
        """
        await initialize_kubernetes(logger)
        self._api_client = ApiClient()

    async def aclose(self) -> None:
        """Cleanly close the Kubernetes API client."""
        if self._api_client:
            await self._api_client.close()
            self._api_client = None


moneypenny_dependency = MoneypennyDependency()
"""The dependency that will return the Moneypenny singleton."""
