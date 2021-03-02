"""Test functions for checking K8s objects.  We do not actually take any
actions in the cluster here; instead, we just check that the in-memory
objects are created correctly.
"""

import json
import os
from typing import Any, Dict, List, Optional

import yaml

import moneypenny

# This should be a fixture.
# Load test cases from the _assets directory
# Set up the environment so the Configuration object finds them.
here = os.path.dirname(os.path.realpath(__file__))
assets = os.path.join(here, "_assets")
with open(os.path.join(assets, "dossier.json")) as f:
    dossier = json.load(f)
cfg = moneypenny.Configuration()
cfg.m_config_path = os.path.join(assets, "m.yaml")
cfg.quips = os.path.join(assets, "quips.txt")
client = moneypenny.KubernetesClient(config=cfg)


def test_make_pod_spec() -> None:
    """
    Build a pod spec from a dossier and an order.
    """

    username = dossier["username"]
    volumes: List[Optional[Dict[str, Any]]] = []
    with open(cfg.m_config_path, "r") as f:
        orders = yaml.safe_load(f)
    containers = orders["commission"]
    podspec = client._make_pod_spec(
        username=username,
        volumes=volumes,
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
    assert vmt["name"] == f"dossier-{username}-vol"
    assert vmt["readOnly"]


def test_make_pod() -> None:
    """Build a pod from a dossier and an order."""
    username = dossier["username"]
    volumes: List[Optional[Dict[str, Any]]] = []
    with open(cfg.m_config_path, "r") as f:
        orders = yaml.safe_load(f)
    containers = orders["commission"]
    pod = client._make_pod(
        username=username,
        volumes=volumes,
        containers=containers,
        dossier=dossier,
    )
    assert pod.metadata.name == f"{username}-pod"


def test_make_configmap() -> None:
    """Build a configmap from a dossier."""
    username = dossier["username"]
    djson = json.dumps(dossier, sort_keys=True, indent=4)
    cmap = client._create_dossier_configmap(dossier=dossier)
    assert cmap.data["dossier.json"] == djson
    assert cmap.metadata.name == f"{username}-cm"
