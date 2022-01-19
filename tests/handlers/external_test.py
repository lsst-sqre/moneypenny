from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from math import log
from unittest.mock import ANY

import pytest
from httpx import AsyncClient
from kubernetes_asyncio.client import (
    V1ConfigMap,
    V1ConfigMapVolumeSource,
    V1ObjectMeta,
    V1OwnerReference,
    V1Pod,
    V1PodSecurityContext,
    V1PodSpec,
    V1PodStatus,
    V1Volume,
)
from safir.testing.kubernetes import MockKubernetesApi

from moneypenny.models import Dossier

from ..support.constants import TEST_HOSTNAME


def url_for(partial_url: str) -> str:
    """Return the full URL for a partial URL."""
    return f"https://{TEST_HOSTNAME}/moneypenny/{partial_url}"


async def wait_for_completion(
    client: AsyncClient, username: str, mock_kubernetes: MockKubernetesApi
) -> None:
    pod_name = f"{username}-pod"
    pod = await mock_kubernetes.read_namespaced_pod(pod_name, "default")
    pod.status = V1PodStatus(phase="Succeeded")

    # Wait a bit for the background thread to run.  It will generally finish
    # way faster than 5s, but this should be robust against overloaded test
    # runners.
    timeout = datetime.now(tz=timezone.utc) + timedelta(seconds=5)
    count = 0
    while datetime.now(tz=timezone.utc) < timeout:
        r = await client.get(f"/moneypenny/users/{username}")
        assert r.status_code == 200
        data = r.json()
        if data["status"] == "active":
            return
        count += 1
        await asyncio.sleep(log(count))
    assert False, "Background thread still not finished after 5s"


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
    r = await client.post("/moneypenny/users", json=dossier.dict())
    assert r.status_code == 303
    assert r.headers["Location"] == url_for(f"users/{dossier.username}")

    r = await client.get(f"/moneypenny/users/{dossier.username}")
    assert r.status_code == 200
    data = r.json()
    assert data == {
        "username": dossier.username,
        "status": "commissioning",
        "last_changed": ANY,
        "uid": dossier.uid,
        "groups": [g.dict() for g in dossier.groups],
    }

    assert mock_kubernetes.get_all_objects_for_test("ConfigMap") == [
        V1ConfigMap(
            metadata=V1ObjectMeta(
                name=f"{dossier.username}-cm",
                namespace="default",
                owner_references=[
                    V1OwnerReference(
                        api_version="v1",
                        kind="Pod",
                        name="moneypenny-78547dcf97-9xqq8",
                        uid="00386592-214f-40c5-88e1-b9657d53a7c6",
                    )
                ],
            ),
            data={
                "dossier.json": json.dumps(
                    dossier.dict(), sort_keys=True, indent=4
                )
            },
        )
    ]
    assert mock_kubernetes.get_all_objects_for_test("Pod") == [
        V1Pod(
            metadata=V1ObjectMeta(
                name=f"{dossier.username}-pod",
                namespace="default",
                owner_references=[
                    V1OwnerReference(
                        api_version="v1",
                        kind="Pod",
                        name="moneypenny-78547dcf97-9xqq8",
                        uid="00386592-214f-40c5-88e1-b9657d53a7c6",
                    )
                ],
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
                                "mountPath": "/homedirs",
                                "name": "homedirs",
                            },
                            {
                                "mountPath": "/opt/dossier",
                                "name": f"dossier-{dossier.username}-vol",
                                "readOnly": True,
                            },
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
                    {
                        "name": "homedirs",
                        "nfs": {
                            "server": "10.10.10.10",
                            "path": "/homedirs",
                        },
                    },
                    V1Volume(
                        name=f"dossier-{dossier.username}-vol",
                        config_map=V1ConfigMapVolumeSource(
                            default_mode=0o644,
                            name=f"{dossier.username}-cm",
                        ),
                    ),
                ],
            ),
            status=V1PodStatus(phase="Running"),
        )
    ]

    await wait_for_completion(client, dossier.username, mock_kubernetes)


@pytest.mark.asyncio
async def test_route_retire(
    client: AsyncClient, dossier: Dossier, mock_kubernetes: MockKubernetesApi
) -> None:
    """Retire is configured to not have any containers."""
    r = await client.post("/moneypenny/users", json=dossier.dict())
    assert r.status_code == 303
    await wait_for_completion(client, dossier.username, mock_kubernetes)

    r = await client.get(f"/moneypenny/users/{dossier.username}")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "active"

    r = await client.post(
        f"/moneypenny/users/{dossier.username}/retire", json=dossier.dict()
    )
    assert r.status_code == 204

    r = await client.get(f"/moneypenny/users/{dossier.username}")
    assert r.status_code == 404

    assert mock_kubernetes.get_all_objects_for_test("ConfigMap") == []
    assert mock_kubernetes.get_all_objects_for_test("Pod") == []


@pytest.mark.asyncio
async def test_simultaneous_orders(
    client: AsyncClient, dossier: Dossier, mock_kubernetes: MockKubernetesApi
) -> None:
    r = await client.post("/moneypenny/users", json=dossier.dict())
    assert r.status_code == 303

    r = await client.post("/moneypenny/users", json=dossier.dict())
    assert r.status_code == 409

    r = await client.post(
        f"/moneypenny/users/{dossier.username}/retire", json=dossier.dict()
    )
    assert r.status_code == 409

    await wait_for_completion(client, dossier.username, mock_kubernetes)


@pytest.mark.asyncio
async def test_repeated_orders(
    client: AsyncClient, dossier: Dossier, mock_kubernetes: MockKubernetesApi
) -> None:
    r = await client.post("/moneypenny/users", json=dossier.dict())
    assert r.status_code == 303

    r = await client.get(f"/moneypenny/users/{dossier.username}")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "commissioning"

    await wait_for_completion(client, dossier.username, mock_kubernetes)

    # Since we've already seen this one, there should be no status change.
    r = await client.post("/moneypenny/users", json=dossier.dict())
    assert r.status_code == 303
    r = await client.get(f"/moneypenny/users/{dossier.username}")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "active"

    # But if we change something about the dossier, we should go through
    # commissioning again.
    new_dossier = dossier.dict()
    new_dossier["uid"] = dossier.uid + 1
    r = await client.post("/moneypenny/users", json=new_dossier)
    assert r.status_code == 303
    r = await client.get(f"/moneypenny/users/{dossier.username}")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "commissioning"
    assert data["uid"] == new_dossier["uid"]

    await wait_for_completion(client, dossier.username, mock_kubernetes)

    r = await client.get(f"/moneypenny/users/{dossier.username}")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "active"
    assert data["uid"] == new_dossier["uid"]
