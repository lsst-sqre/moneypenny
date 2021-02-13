"""Kubernetes client abstraction for Moneypenny."""

from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog
from yaml import safe_load
from kubernetes.client import (
    V1Capabilities,
    V1Container,
    V1LocalObjectReference,
    V1ObjectMeta,
    V1PodSecurityContext,
    V1PodSpec,
    V1SecurityContext,
)
from kubernetes.client.api import core_v1_api
from kubernetes.client.exceptions import ApiException

from .types import OperationFailed, PodNotFound, K8sApiException

NAMESPACE_FILE = "/var/run/secrets/kubernetes.io/serviceaccount/namespace"
PRIMARY_CONTAINER_IMAGE = "library/alpine:latest"

logger = structlog.get_logger(__name__)


class KubernetesClient:
    """A client for moneypenny's usage of Kubernetes.

    This provides a level of abstraction away from the python-kubernetes
    objects and models.  By hiding these obscure objects here it makes
    the code easier to mock and test.
    """

    def __init__(self) -> None:
        """Create a new client for the cluster we are running in."""
        self.namespace = Path(NAMESPACE_FILE).read_text().strip()
        self.api = core_v1_api.CoreV1Api()

    def make_pod(self,
                 name: str,
                 initContainers: List[Any],
                 dossier: Dict[str, Any]):
        """Create a new Pod with provisioning initContainers.

        Parameters
        ----------
        name: Name of the pod.  This can be used to identify the pods in
          kubectl.
        init_containers: This is the list of initContainers to be run,
          in sequence.  The format is exactly what is deserialized with
          yaml.safe_load().
        dossier: This is a dictionary that has the format of a token
          returned by Gafaelfawr.
        """
        podspec = self._make_pod_spec(name, initContainers, dossier)
        self.api.create_pod(self.namespace, podspec)
        
    
    def _make_pod_spec(
            self,
            name: str,
            initContainers: List[Any],
            dossier: Dict[str, Any]
    ):
        """This is its own method for unit testing."""
        primary_container = V1Container(
            name="primary",
            args = [ "/bin/true" ],
            image=PRIMARY_CONTAINER_IMAGE,
            security_context=V1SecurityContext(
                allow_privilege_escalation=False,
                capabilities=V1Capabilities(drop=["ALL"]),
                read_only_root_filesystem=True,
            ),
        )

        if pull_secret_name:
            pull_secret = [V1LocalObjectReference(name=pull_secret_name)]
        else:
            pull_secret = []

        pod_spec=V1PodSpec(
            automount_service_account_token=False,
            containers=[primary_container],
            init_containers=init_containers,
            image_pull_secrets=pull_secret,
            node_selector=labels,
            security_context=V1PodSecurityContext(
                run_as_non_root=True,
                run_as_group=1000,
                run_as_user=1000,
            ),
        )
        return pod_spec


    def pod_delete(self, name: str) -> None:
        """Delete the pod of the given name."""
        try:
            logger.info(f"Deleting pod {name}")
            status = self.api.delete_namespaced_pod(
                name, self.namespace
            )
            logger.debug(f"Pod {name} deleted: {status}")
        except ApiException as exc:
            logger.exception("Exception deleting pod")
            raise K8sApiException(exc)

    def _pod_status(self, name: str) -> str:
        """Return the status of the pod with the given name.

        Parameters
        ----------
        name: Name of the pod to check on.

        Returns
        -------
        The pod status: https://kubernetes.io/docs/reference/generated/kubernetes-api/v1.20/#podstatus-v1-core

        """
        try:
            logger.info(f"Checking status for pod {name}")
            pod = self.apps_api.read_namespaced_pod(
                name, self.namespace
            )
        except ApiException as exc:
            logger.exception("Exception reading pod")
            raise K8sApiException(exc)
        return pod.status

    def pod_completed(self, name: str) -> bool:
        """Return true if the pod completed successfully, false if it
        is pending or running, and raise an exception if any part of the
        execution failed.
        
        Parameters
        ----------
        name: Name of the pod to check on.

        Returns
        -------
        True for successful completion, False for still-in-progress.

        Raises
        ------
        OperationFailed if the pod encountered an error.
        """

        try:
            status=self._pod_status(name)
        except ApiException as exc:
            if exc.status == 404:
                raise PodNotFound(f"Pod {name} not found")
            raise K8sApiException(exc)
        phase = status.phase
        if phase == "Succeeded":
            return True
        if phase == "Pending" or "Running":
            return False
        if phase == "Unknown":
            raise OperationFailed(f"Pod {name} in Unknown phase")
        raise OperationFailed(status.message)
        
