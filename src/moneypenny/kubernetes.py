"""Kubernetes client abstraction for Moneypenny."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import kubernetes_asyncio
from kubernetes_asyncio.client import (
    ApiClient,
    CoreV1Api,
    V1ConfigMap,
    V1ConfigMapVolumeSource,
    V1LocalObjectReference,
    V1ObjectMeta,
    V1OwnerReference,
    V1Pod,
    V1PodSecurityContext,
    V1PodSpec,
    V1Volume,
)
from kubernetes_asyncio.client.exceptions import ApiException
from kubernetes_asyncio.config import ConfigException

from .config import config
from .exceptions import K8sApiException, OperationFailed, PodNotFound
from .models import Dossier

if TYPE_CHECKING:
    from types import TracebackType
    from typing import Any, Dict, List, Literal, Optional, Type

    from structlog.stdlib import BoundLogger


async def initialize_kubernetes(logger: BoundLogger) -> None:
    """Load the Kubernetes configuration.

    This has to be run once per process and should be run during application
    startup.  This function handles Kubernetes configuration independent of
    any given Kubernetes client so that clients can be created for each
    request.
    """
    try:
        kubernetes_asyncio.config.load_incluster_config()
    except ConfigException:
        logger.warn("In-cluster config failed; trying kube_config")
        await kubernetes_asyncio.config.load_kube_config()


def read_namespace(logger: BoundLogger) -> str:
    """Determine the namespace of the pod from the Kubernetes metadata.

    Parameters
    ----------
    logger : `structlog.stdlib.BoundLogger`
        Logger to use for warnings if the namespace file couldn't be found.

    Returns
    -------
    namespace : `str`
        The namespace, or ``default`` if the namespace file is not present.
    """
    path = Path("/var/run/secrets/kubernetes.io/serviceaccount/namespace")
    try:
        return path.read_text().strip()
    except FileNotFoundError:
        logger.warn(f"Namespace file {str(path)} not found, using 'default'")
        return "default"


def read_pod_info(filename: str) -> str:
    """Read the file containing some information about our current pod.

    This data is provided as files mounted into the container by Kubernetes.

    Parameters
    ----------
    filename : `str`
        Filename to read in ``/etc/podinfo``.  The list is available in the
        Helm chart.

    Returns
    -------
    contents : `str`
        Contents of that file.
    """
    return (Path(config.podinfo_dir) / filename).read_text()


def _name_object(username: str, type: str) -> str:
    """This constructs a consistent object name from the username and
    type.  Purely syntactic sugar, but tasty and widely used in here.
    """
    return f"{username}-{type}"


class KubernetesClient:
    """A client for moneypenny's usage of Kubernetes.

    This provides a level of abstraction away from the python-kubernetes
    objects and models.  By hiding these obscure objects here it makes
    the code easier to mock and test.

    The public API is just three methods: make_objects, delete_objects,
    and check_pod_completed.

    All Exceptions raised are our own, although they may well be thin
    wrappers around the corresponding K8s API error.

    This should normally be used inside an ``async with`` block so that the
    client will automatically be cleaned up when no longer needed.  If not
    used that way, `aclose` must be called when finished using the client.
    """

    def __init__(self, logger: BoundLogger) -> None:
        self.logger = logger
        self.namespace = read_namespace(logger)
        self.api = ApiClient()
        self.v1 = CoreV1Api(self.api)

    async def __aenter__(self) -> KubernetesClient:
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> Literal[False]:
        await self.aclose()
        return False

    async def aclose(self) -> None:
        """Close the Kubernetes API client."""
        await self.api.close()

    async def make_objects(
        self,
        username: str,
        volumes: List[Optional[Dict[str, Any]]],
        containers: List[Dict[str, Any]],
        dossier: Dossier,
        pull_secret_name: Optional[str] = None,
    ) -> None:
        """Create a new Pod with provisioning initContainers along with
        its ConfigMap containing the dossier.

        Parameters
        ----------
        username: Username for the pod to be created.
        volumes: This is the list of Volumes to be mounted to the pod; in
          the usual case, it's a one-item list specifying the (read-write)
          filestore that contains the user home directories.
        containers: This is the list of containers to be run, in sequence.
          The format is exactly what is deserialized with yaml.safe_load().
        dossier: This is a dictionary that has the format of a token
          returned by Gafaelfawr.
        pull_secret_name: name of the secret in the current namespace
          (if any) used to pull Docker images.
        """
        pod = self._make_pod(
            username=username,
            volumes=volumes,
            containers=containers,
            dossier=dossier,
            pull_secret_name=pull_secret_name,
        )
        dossier_cm = self._create_dossier_configmap(dossier)
        self.logger.info(f"Creating configmap for {username}")
        try:
            status = await self.v1.create_namespaced_config_map(
                self.namespace, dossier_cm
            )
        except ApiException as e:
            self.logger.exception("Exception creating configmap")
            raise K8sApiException(e)
        self.logger.debug(f"Configmap for {username} created: {status}")
        self.logger.info(f"Creating pod for {username}")
        try:
            status = await self.v1.create_namespaced_pod(self.namespace, pod)
        except ApiException as e:
            self.logger.exception("Exception creating pod")
            raise K8sApiException(e)
        self.logger.debug(f"Pod for {username} created: {status}")

    async def delete_objects(self, username: str) -> None:
        """Delete both the pod and its associated configmap, given a
        username.

        Parameters
        ----------
        name: Username for the pod and configmap to delete.

        Raises
        ------
        K8sApiException if the deletion failed.
        """
        # Do the configmap first, because we may get here as a result of
        #  a pod failure, and so the pod_delete will throw an error if it's
        #  already gone or never existed in the first place.
        try:
            await self._configmap_delete(username)
        except Exception as exc:
            self.logger.error(
                f"Deleting configmap for {username} failed: {exc}"
            )
        await self._pod_delete(username)

    async def check_pod_completed(self, username: str) -> bool:
        """Return true if the pod completed successfully, false if it
        is pending or running, and raise an exception if any part of the
        execution failed.

        Parameters
        ----------
        name: Username for the pod to check on.

        Returns
        -------
        True for successful completion, False for still-in-progress.

        Raises
        ------
        PodNotFound if the pod isn't there at all, OperationFailed if the pod
        encountered an error, K8sApiException for some other Kubernetes error.
        """
        pname = _name_object(username, "pod")
        try:
            pod = await self.v1.read_namespaced_pod(pname, self.namespace)
            status = pod.status
        except ApiException as exc:
            if exc.status == 404:
                raise PodNotFound(f"Pod {pname} not found")
            self.logger.exception("Error checking on pod completion")
            raise K8sApiException(exc)
        phase: str = status.phase
        if phase == "Succeeded":
            return True
        elif phase in ("Pending", "Running"):
            return False
        elif phase == "Unknown":
            raise OperationFailed(f"Pod {pname} in Unknown phase")
        else:
            # phase == "Failed"
            raise OperationFailed(f"Pod {pname} failed: {status.message}")

    def _make_pod(
        self,
        username: str,
        volumes: List[Optional[Dict[str, Any]]],
        containers: List[Dict[str, Any]],
        dossier: Dossier,
        pull_secret_name: Optional[str] = None,
    ) -> V1Pod:
        spec = self._make_pod_spec(
            username=username,
            volumes=volumes,
            containers=containers,
            dossier=dossier,
            pull_secret_name=pull_secret_name,
        )
        pname = _name_object(username, "pod")
        md = V1ObjectMeta(
            name=pname,
            namespace=self.namespace,
            owner_references=[
                V1OwnerReference(
                    api_version="v1",
                    kind="Pod",
                    name=read_pod_info("name"),
                    uid=read_pod_info("uid"),
                )
            ],
        )
        pod = V1Pod(metadata=md, spec=spec)
        return pod

    def _make_pod_spec(
        self,
        username: str,
        volumes: List[Optional[Dict[str, Any]]],
        containers: List[Dict[str, Any]],
        dossier: Dossier,
        pull_secret_name: Optional[str] = None,
    ) -> V1PodSpec:
        """This is its own method for unit testing.  It just defines the
        in-memory K8s object corresponding to the Pod."""
        main_container = containers[-1]  # We must always have at least one.
        init_containers = []
        if len(containers) > 1:
            init_containers = containers[:-1]

        if pull_secret_name:
            pull_secret = [V1LocalObjectReference(name=pull_secret_name)]
        else:
            pull_secret = []

        self._add_dossier_vol(dossier, containers)
        username = dossier.username
        vname = _name_object(f"dossier-{username}", "vol")
        cmname = _name_object(username, "cm")
        volumes.append(
            V1Volume(
                name=vname,
                config_map=V1ConfigMapVolumeSource(
                    default_mode=0o644, name=cmname
                ),
            )
        )
        sec_ctx = V1PodSecurityContext(
            # This will largely be overridden by init containers
            run_as_group=1000,
            run_as_user=1000,
        )
        pod_spec = V1PodSpec(
            automount_service_account_token=False,
            containers=[main_container],
            init_containers=init_containers,
            image_pull_secrets=pull_secret,
            # node_selector=labels,
            restart_policy="OnFailure",
            security_context=sec_ctx,
            volumes=volumes,
        )
        return pod_spec

    def _create_dossier_configmap(self, dossier: Dossier) -> V1ConfigMap:
        """Build the configmap containing the dossier that will be
        mounted to the working container.  Dossier will be in JSON
        format, purely because Python includes a json parser but not
        a yaml parser in its standard library.
        """
        cmname = _name_object(dossier.username, "cm")
        djson = json.dumps(dossier.dict(), sort_keys=True, indent=4)
        data = {"dossier.json": djson}
        cm = V1ConfigMap(
            metadata=V1ObjectMeta(
                name=cmname,
                namespace=self.namespace,
                owner_references=[
                    V1OwnerReference(
                        api_version="v1",
                        kind="Pod",
                        name=read_pod_info("name"),
                        uid=read_pod_info("uid"),
                    )
                ],
            ),
            data=data,
        )
        return cm

    def _add_dossier_vol(
        self, dossier: Dossier, containers: List[Any]
    ) -> None:
        """Updates containers in place."""
        vname = _name_object(f"dossier-{dossier.username}", "vol")
        for ctr in containers:
            if not ctr.get("volumeMounts"):
                ctr["volumeMounts"] = []
            ctr["volumeMounts"].append(
                {
                    "name": vname,
                    "mountPath": config.dossier_path,
                    "readOnly": True,
                }
            )

    async def _configmap_delete(self, username: str) -> None:
        """Delete the ConfigMap for the given name."""
        cmname = _name_object(username, "cm")
        try:
            status = await self.v1.delete_namespaced_config_map(
                name=cmname, namespace=self.namespace
            )
        except ApiException as e:
            self.logger.exception("Exception deleting configmap")
            raise K8sApiException(e)
        self.logger.debug(f"Configmap {cmname} deleted: {status}")

    async def _pod_delete(self, username: str) -> None:
        """Delete the pod for the given username."""
        self.logger.info(f"Deleting pod for {username}")
        pname = _name_object(username, "pod")
        try:
            status = await self.v1.delete_namespaced_pod(pname, self.namespace)
        except ApiException as exc:
            self.logger.exception("Exception deleting pod")
            raise K8sApiException(exc)
        self.logger.debug(f"Pod {pname} deleted: {status}")
