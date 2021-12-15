from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from math import log
from typing import TYPE_CHECKING
from unittest.mock import ANY

import pytest
from kubernetes_asyncio.client import (
    V1ConfigMap,
    V1ConfigMapVolumeSource,
    V1ObjectMeta,
    V1Pod,
    V1PodSecurityContext,
    V1PodSpec,
    V1PodStatus,
    V1Volume,
)

from tests.support.constants import TEST_HOSTNAME
from tests.support.kubernetes import assert_kubernetes_objects_are

if TYPE_CHECKING:
    from httpx import AsyncClient

    from moneypenny.models import Dossier
    from tests.support.kubernetes import MockKubernetesApi


def url_for(partial_url: str) -> str:
    """Return the full URL for a partial URL."""
    return f"https://{TEST_HOSTNAME}/moneypenny/{partial_url}"


@pytest.mark.asyncio
async def test_route_index(client: AsyncClient) -> None:
    r = await client.get("/moneypenny/")
    assert r.status_code == 200
    assert r.json() == {
        "quip": "Flattery will get you nowhere... but don't stop trying.",
        "metadata": ANY,
    }


@pytest.mark.asyncio
async def test_route_commission(
    client: AsyncClient, dossier: Dossier, mock_kubernetes: MockKubernetesApi
) -> None:
    r = await client.post("/moneypenny/commission", json=dossier.dict())
    assert r.status_code == 303
    assert r.headers["Location"] == url_for(dossier.username)

    r = await client.get(f"/moneypenny/{dossier.username}")
    assert r.status_code == 202

    assert_kubernetes_objects_are(
        mock_kubernetes,
        "ConfigMap",
        [
            V1ConfigMap(
                metadata=V1ObjectMeta(
                    name=f"{dossier.username}-cm", namespace="default"
                ),
                data={
                    "dossier.json": json.dumps(
                        dossier.dict(), sort_keys=True, indent=4
                    )
                },
            )
        ],
    )
    assert_kubernetes_objects_are(
        mock_kubernetes,
        "Pod",
        [
            V1Pod(
                metadata=V1ObjectMeta(
                    name=f"{dossier.username}-pod",
                    namespace="default",
                ),
                spec=V1PodSpec(
                    automount_service_account_token=False,
                    containers=[
                        {
                            "name": "farthing",
                            "image": "lsstsqre/farthing",
                            "securityContext": {
                                "runAsUser": 1000,
                                "runAsNonRootUser": True,
                                "allowPrivilegeEscalation": False,
                            },
                            "volumeMounts": [
                                {
                                    "mountPath": "/opt/dossier",
                                    "name": f"dossier-{dossier.username}-vol",
                                    "readOnly": True,
                                }
                            ],
                        }
                    ],
                    image_pull_secrets=[],
                    init_containers=[],
                    restart_policy="OnFailure",
                    security_context=V1PodSecurityContext(
                        run_as_group=1000, run_as_user=1000
                    ),
                    volumes=[
                        V1Volume(
                            name=f"dossier-{dossier.username}-vol",
                            config_map=V1ConfigMapVolumeSource(
                                default_mode=0o644,
                                name=f"{dossier.username}-cm",
                            ),
                        )
                    ],
                ),
                status=V1PodStatus(phase="Running"),
            )
        ],
    )

    r = await client.get(f"/moneypenny/{dossier.username}")
    assert r.status_code == 202

    pod_name = f"{dossier.username}-pod"
    pod = await mock_kubernetes.read_namespaced_pod(pod_name, "default")
    pod.status = V1PodStatus(phase="Succeeded")

    r = await client.get(f"/moneypenny/{dossier.username}")
    assert r.status_code in (200, 404)

    # Wait a bit for the background thread to run.  It will generally finish
    # way faster than 5s, but this should be robust against overloaded test
    # runners.
    timeout = datetime.now(tz=timezone.utc) + timedelta(seconds=5)
    count = 1
    while r.status_code == 200 and datetime.now(tz=timezone.utc) < timeout:
        await asyncio.sleep(log(count))
        r = await client.get(f"/moneypenny/{dossier.username}")
        assert r.status_code in (200, 404)


@pytest.mark.asyncio
async def test_route_retire(
    client: AsyncClient, dossier: Dossier, mock_kubernetes: MockKubernetesApi
) -> None:
    r = await client.post("/moneypenny/retire", json=dossier.dict())
    assert r.status_code == 303
    assert r.headers["Location"] == url_for(dossier.username)

    r = await client.get(f"/moneypenny/{dossier.username}")
    assert r.status_code == 202

    assert_kubernetes_objects_are(
        mock_kubernetes,
        "ConfigMap",
        [
            V1ConfigMap(
                metadata=V1ObjectMeta(
                    name=f"{dossier.username}-cm", namespace="default"
                ),
                data={
                    "dossier.json": json.dumps(
                        dossier.dict(), sort_keys=True, indent=4
                    )
                },
            )
        ],
    )
    assert_kubernetes_objects_are(
        mock_kubernetes,
        "Pod",
        [
            V1Pod(
                metadata=V1ObjectMeta(
                    name=f"{dossier.username}-pod",
                    namespace="default",
                ),
                spec=V1PodSpec(
                    automount_service_account_token=False,
                    containers=[
                        {
                            "name": "farthing",
                            "image": "lsstsqre/farthing",
                            "securityContext": {
                                "runAsUser": 1000,
                                "runAsNonRootUser": True,
                                "allowPrivilegeEscalation": False,
                            },
                            "volumeMounts": [
                                {
                                    "mountPath": "/opt/dossier",
                                    "name": f"dossier-{dossier.username}-vol",
                                    "readOnly": True,
                                }
                            ],
                        }
                    ],
                    image_pull_secrets=[],
                    init_containers=[],
                    restart_policy="OnFailure",
                    security_context=V1PodSecurityContext(
                        run_as_group=1000, run_as_user=1000
                    ),
                    volumes=[
                        V1Volume(
                            name=f"dossier-{dossier.username}-vol",
                            config_map=V1ConfigMapVolumeSource(
                                default_mode=0o644,
                                name=f"{dossier.username}-cm",
                            ),
                        )
                    ],
                ),
                status=V1PodStatus(phase="Running"),
            )
        ],
    )

    r = await client.get(f"/moneypenny/{dossier.username}")
    assert r.status_code == 202

    pod_name = f"{dossier.username}-pod"
    pod = await mock_kubernetes.read_namespaced_pod(pod_name, "default")
    pod.status = V1PodStatus(phase="Succeeded")

    r = await client.get(f"/moneypenny/{dossier.username}")
    assert r.status_code in (200, 404)

    # Wait a bit for the background thread to run.  It will generally finish
    # way faster than 5s, but this should be robust against overloaded test
    # runners.
    timeout = datetime.now(tz=timezone.utc) + timedelta(seconds=5)
    count = 1
    while r.status_code == 200 and datetime.now(tz=timezone.utc) < timeout:
        await asyncio.sleep(log(count))
        r = await client.get(f"/moneypenny/{dossier.username}")
        assert r.status_code in (200, 404)


@pytest.mark.asyncio
async def test_simultaneous_orders(
    client: AsyncClient, dossier: Dossier, mock_kubernetes: MockKubernetesApi
) -> None:
    r = await client.post("/moneypenny/commission", json=dossier.dict())
    assert r.status_code == 303
    assert r.headers["Location"] == url_for(dossier.username)
    r = await client.post("/moneypenny/commission", json=dossier.dict())
    assert r.status_code == 409

    pod_name = f"{dossier.username}-pod"
    pod = await mock_kubernetes.read_namespaced_pod(pod_name, "default")
    pod.status = V1PodStatus(phase="Succeeded")

    while r.status_code != 404:
        r = await client.get(f"/moneypenny/{dossier.username}")
        await asyncio.sleep(0.5)
