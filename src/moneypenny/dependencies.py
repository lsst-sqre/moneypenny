"""FastAPI dependencies for Moneypenny."""

from typing import Optional

from .kubernetes import KubernetesClient
from .moneypenny import Moneypenny


class MoneypennyDependency:
    """Maintains a singleton Moneypenny class used by all handlers."""

    def __init__(self) -> None:
        self.moneypenny: Optional[Moneypenny] = None

    async def __call__(self) -> Moneypenny:
        assert self.moneypenny, "moneypenny_dependency not initialized"
        return self.moneypenny

    async def initialize(self) -> None:
        """Initialize the dependency.

        This must be called during application startup.
        """
        self.k8s_client = await KubernetesClient.create()
        self.moneypenny = Moneypenny(self.k8s_client)

    async def aclose(self) -> None:
        """Cleanly close resources used by the Moneypenny singleton."""
        if self.moneypenny:
            await self.k8s_client.aclose()
            self.moneypenny = None


moneypenny_dependency = MoneypennyDependency()
"""The dependency that will return the Moneypenny singleton."""
