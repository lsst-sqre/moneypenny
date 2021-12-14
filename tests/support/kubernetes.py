"""Mock Kubernetes API for testing."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import Mock

import kubernetes_asyncio
from kubernetes_asyncio.client import (
    ApiException,
    V1ConfigMap,
    V1Pod,
    V1PodStatus,
    V1Status,
)

if TYPE_CHECKING:
    from typing import Any, Callable, Dict, List, Optional

__all__ = ["MockKubernetesApi", "assert_kubernetes_objects_are"]


def assert_kubernetes_objects_are(
    mock_kubernetes: MockKubernetesApi, kind: str, expected: List[Any]
) -> None:
    """Assert that Kubernetes contains only the specified models."""
    seen = mock_kubernetes.get_all_objects_for_test(kind)
    expected_sorted = sorted(
        expected, key=lambda o: (o.metadata.namespace, o.kind, o.metadata.name)
    )
    assert seen == expected_sorted


class MockKubernetesApi(Mock):
    """Mock Kubernetes API for testing.

    This object simulates (with almost everything left out) the
    `kubernetes.client.CoreV1Api` and `kubernetes.client.CustomObjectApi`
    client objects while keeping simple internal state.  It is intended to be
    used as a mock inside tests.

    Methods ending with ``_for_test`` are outside of the API and are intended
    for use by the test suite.
    """

    def __init__(self) -> None:
        super().__init__(spec=kubernetes_asyncio.client.CoreV1Api)
        self.error_callback: Optional[Callable[..., None]] = None
        self.objects: Dict[str, Dict[str, Dict[str, Any]]] = {}

    def get_all_objects_for_test(self, kind: str) -> List[Any]:
        """Return all objects of a given kind sorted by namespace and name."""
        results = []
        for namespace in sorted(self.objects.keys()):
            if kind not in self.objects[namespace]:
                continue
            for name in sorted(self.objects[namespace][kind].keys()):
                results.append(self.objects[namespace][kind][name])
        return results

    def _maybe_error(self, method: str, *args: Any) -> None:
        """Helper function to avoid using class method call syntax."""
        if self.error_callback:
            callback = self.error_callback
            callback(method, *args)

    # CONFIGMAP API

    async def create_namespaced_config_map(
        self, namespace: str, config_map: V1ConfigMap
    ) -> None:
        self._maybe_error(
            "create_namespaced_config_map", namespace, config_map
        )
        assert namespace == config_map.metadata.namespace
        name = config_map.metadata.name
        if namespace not in self.objects:
            self.objects[namespace] = {}
        if "ConfigMap" not in self.objects[namespace]:
            self.objects[namespace]["ConfigMap"] = {}
        if name in self.objects[namespace]["ConfigMap"]:
            raise ApiException(status=500, reason=f"{namespace}/{name} exists")
        self.objects[namespace]["ConfigMap"][name] = config_map

    async def delete_namespaced_config_map(
        self, name: str, namespace: str
    ) -> V1Status:
        self._maybe_error("delete_namespaced_config_map", name, namespace)
        if namespace not in self.objects:
            reason = f"{namespace}/{name} not found"
            raise ApiException(status=404, reason=reason)
        if name not in self.objects[namespace].get("ConfigMap", {}):
            reason = f"{namespace}/{name} not found"
            raise ApiException(status=404, reason=reason)
        del self.objects[namespace]["ConfigMap"][name]
        return V1Status(code=200)

    # POD API

    async def create_namespaced_pod(self, namespace: str, pod: V1Pod) -> None:
        self._maybe_error("create_namespaced_pod", namespace, pod)
        assert namespace == pod.metadata.namespace
        name = pod.metadata.name
        if namespace not in self.objects:
            self.objects[namespace] = {}
        if "Pod" not in self.objects[namespace]:
            self.objects[namespace]["Pod"] = {}
        if name in self.objects[namespace]["Pod"]:
            raise ApiException(status=500, reason=f"{namespace}/{name} exists")
        pod.status = V1PodStatus(phase="Running")
        self.objects[namespace]["Pod"][name] = pod

    async def delete_namespaced_pod(
        self, name: str, namespace: str
    ) -> V1Status:
        self._maybe_error("delete_namespaced_pod", name, namespace)
        if namespace not in self.objects:
            reason = f"{namespace}/{name} not found"
            raise ApiException(status=404, reason=reason)
        if name not in self.objects[namespace].get("Pod", {}):
            reason = f"{namespace}/{name} not found"
            raise ApiException(status=404, reason=reason)
        del self.objects[namespace]["Pod"][name]
        return V1Status(code=200)

    async def read_namespaced_pod(self, name: str, namespace: str) -> V1Pod:
        self._maybe_error("read_namespaced_pod", name, namespace)
        if namespace not in self.objects:
            reason = f"{namespace}/{name} not found"
            raise ApiException(status=404, reason=reason)
        if name not in self.objects[namespace].get("Pod", {}):
            reason = f"{namespace}/{name} not found"
            raise ApiException(status=404, reason=reason)
        return self.objects[namespace]["Pod"][name]
