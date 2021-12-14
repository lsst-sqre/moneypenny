"""Test functions for checking K8s objects.  We do not actually take any
actions in the cluster here; instead, we just check that the in-memory
objects are created correctly.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import yaml

from moneypenny.config import config
from moneypenny.kubernetes import KubernetesClient

if TYPE_CHECKING:
    from fastapi import FastAPI

    from moneypenny.models import Dossier


def test_make_pod_spec(app: FastAPI, dossier: Dossier) -> None:
    """Build a pod spec from a dossier and an order."""
    client = KubernetesClient(MagicMock())
    with open(config.m_config_path, "r") as f:
        orders = yaml.safe_load(f)
    containers = orders["commission"]
    podspec = client._make_pod_spec(
        username=dossier.username,
        volumes=[],
        containers=containers,
        dossier=dossier,
    )

    # Verify the podspec has the characteristics we expect
    assert podspec.security_context.run_as_user == 1000
    assert podspec.security_context.run_as_group == 1000
    assert not podspec.init_containers and podspec.init_containers is not None
    assert len(podspec.containers) == 1

    # The container is a dict rather than a K8s object
    ctr = podspec.containers[0]
    assert ctr["name"] == "farthing"
    assert ctr["image"] == "lsstsqre/farthing"
    assert ctr["securityContext"]["runAsUser"] == 1000
    assert ctr["securityContext"]["runAsNonRootUser"]
    assert not ctr["securityContext"]["allowPrivilegeEscalation"]
    vmt = ctr["volumeMounts"][0]
    assert vmt["mountPath"] == "/opt/dossier"
    assert vmt["name"] == f"dossier-{dossier.username}-vol"
    assert vmt["readOnly"]


def test_make_pod(app: FastAPI, dossier: Dossier) -> None:
    """Build a pod from a dossier and an order."""
    client = KubernetesClient(MagicMock())
    with open(config.m_config_path, "r") as f:
        orders = yaml.safe_load(f)
    containers = orders["commission"]
    pod = client._make_pod(
        username=dossier.username,
        volumes=[],
        containers=containers,
        dossier=dossier,
    )
    assert pod.metadata.name == f"{dossier.username}-pod"


def test_make_configmap(app: FastAPI, dossier: Dossier) -> None:
    """Build a configmap from a dossier."""
    client = KubernetesClient(MagicMock())
    djson = json.dumps(dossier.dict(), sort_keys=True, indent=4)
    cmap = client._create_dossier_configmap(dossier=dossier)
    assert cmap.data["dossier.json"] == djson
    assert cmap.metadata.name == f"{dossier.username}-cm"
