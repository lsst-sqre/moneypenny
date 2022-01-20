"""Support functions for Kubernetes tests."""

from __future__ import annotations

from asyncio import Queue
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Tuple


class MockKubernetesStream:
    """Represents a stream returned by a watch object."""

    def __init__(
        self,
        queue: Queue[str],
        api_call: Callable[..., Awaitable[Any]],
        args: Tuple[Any, ...],
        kwargs: Dict[str, Any],
    ) -> None:
        self.queue = queue
        self.api_call = api_call
        self.args = args
        self.kwargs = kwargs
        self.objects: List[Any] = []

    def __aiter__(self) -> MockKubernetesStream:
        return self

    async def __anext__(self) -> Dict[str, Any]:
        api_call = self.api_call
        if self.objects:
            return {"object": self.objects.pop(0)}
        await self.queue.get()
        result = await api_call(*self.args, **self.kwargs)
        self.objects = result.items
        return {"object": self.objects.pop(0)}


class MockKubernetesWatch:
    """Mock the watch API for Kubernetes.

    This is a very partial implementation of the watch API that allows a test
    to trigger new watch events via an asyncio Queue.
    """

    def __init__(self) -> None:
        self.queue: Queue[str] = Queue()

    @asynccontextmanager
    async def stream(
        self,
        api_call: Callable[..., Awaitable[Any]],
        *args: Any,
        **kwargs: Any,
    ) -> AsyncIterator[MockKubernetesStream]:
        await self.queue.put("")
        yield MockKubernetesStream(self.queue, api_call, args, kwargs)

    async def signal_change(self) -> None:
        await self.queue.put("")
