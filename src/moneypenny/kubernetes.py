"""Kubernetes client abstraction for Moneypenny."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING

from kubernetes_asyncio import client, watch
from kubernetes_asyncio.client import (
    V1ConfigMap,
    V1ConfigMapVolumeSource,
    V1LocalObjectReference,
    V1ObjectMeta,
    V1OwnerReference,
    V1Pod,
    V1PodSecurityContext,
    V1PodSpec,
    V1PodStatus,
    V1Volume,
)
from kubernetes_asyncio.client.exceptions import ApiException

from .config import config
from .exceptions import K8sApiException, OperationFailed, PodNotFound
from .models import Dossier

if TYPE_CHECKING:
    from typing import Any, Dict, List, Optional

    from structlog.stdlib import BoundLogger


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

    All Exceptions raised are our own, although they may well be thin
    wrappers around the corresponding K8s API error.
    """

    def __init__(
        self, api_client: client.ApiClient, logger: BoundLogger
    ) -> None:
        self.v1 = client.CoreV1Api(api_client)
        self.logger = logger
        self.namespace = read_namespace(logger)

    async def make_objects(
        self,
        username: str,
        volumes: List[Dict[str, Any]],
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

        await self.delete_objects(username)

        count = 1
        while True:
            msg = f"Creating ConfigMap for {username} (try #{count})"
            self.logger.info(msg)
            try:
                status = await self.v1.create_namespaced_config_map(
                    self.namespace, dossier_cm
                )
            except ApiException as e:
                msg = f"Exception creating ConfigMap for {username}"
                self.logger.exception(msg)
                if count > 5:
                    raise K8sApiException(e)
                else:
                    await asyncio.sleep(1)
                    self.logger.info(f"Retrying ConfigMap for {username}")
            else:
                msg = f"ConfigMap for {username} created: {status}"
                self.logger.debug(msg)
                break
            count += 1

        count = 1
        while True:
            self.logger.info(f"Creating Pod for {username} (try #{count})")
            try:
                status = await self.v1.create_namespaced_pod(
                    self.namespace, pod
                )
            except ApiException as e:
                self.logger.exception(f"Exception creating Pod for {username}")
                if count > 5:
                    try:
                        await self._configmap_delete(username)
                    except K8sApiException:
                        msg = f"Failed to delete ConfigMap for {username}"
                        self.logger.exception(msg)
                    raise K8sApiException(e)
                else:
                    await asyncio.sleep(1)
                    self.logger.info(f"Retrying Pod for {username}")
            else:
                self.logger.debug(f"Pod for {username} created: {status}")
                break
            count += 1

    async def delete_objects(self, username: str) -> None:
        """Delete the Pod and ConfigMap for a user.

        Parameters
        ----------
        username : `str`
            Username for the pod and configmap to delete.

        Raises
        ------
        moneypenny.exceptions.K8sApiException
            If the deletion failed.
        """
        await self._configmap_delete(username)
        await self._pod_delete(username)

    async def wait_for_pod(self, username: str) -> None:
        """Wait for the pod for a user to complete.

        Parameters
        ----------
        username : `str`
            Username of user whose pod to wait for.

        Raises
        ------
        moneypenny.exceptions.PodNotFound
            The user's pod is not there at all.
        moneypenny.exceptions.OperationFailed
            The pod failed.
        moneypenny.exceptions.K8sApiException
            Some other Kubernetes API failure.
        """
        pod_name = _name_object(username, "pod")
        args = (self.v1.list_namespaced_pod, self.namespace)
        kwargs = {"field_selector": f"metadata.name={pod_name}"}
        try:
            async with watch.Watch().stream(*args, **kwargs) as stream:
                async for event in stream:
                    status = event["object"].status
                    msg = f"New status of {pod_name}: {status.phase}"
                    self.logger.debug(msg)
                    if self._is_pod_finished(pod_name, status):
                        return
        except ApiException as e:
            if e.status == 404:
                raise PodNotFound(f"Pod {pod_name} not found")
            msg = "Error checking on {pod_name} pod completion"
            self.logger.exception(msg)
            raise K8sApiException(e)

    def _is_pod_finished(self, name: str, status: V1PodStatus) -> bool:
        """Return true if a pod is finished, false if it is still running.

        Parameters
        ----------
        name : `str`
            The name of the pod, for error reporting.
        status : ``kubernetes_asyncio.client.V1PodStatus``
            The status information for the pod.

        Raises
        ------
        moneypenny.exceptions.PodNotFound
            The user's pod is not there at all.
        moneypenny.exceptions.OperationFailed
            The pod failed.
        moneypenny.exceptions.K8sApiException
            Some other Kubernetes API failure.
        """
        if status.phase == "Succeeded":
            return True
        elif status.phase == "Unknown":
            raise OperationFailed(f"Pod {name} in Unknown phase")
        elif status.phase == "Failed":
            raise OperationFailed(f"Pod {name} failed: {status.message}")
        elif status.phase in ("Pending", "Running"):
            return False
        else:
            msg = f"Pod {name} has unknown phase {status.phase}"
            raise OperationFailed(msg)

    def _make_pod(
        self,
        username: str,
        volumes: List[Dict[str, Any]],
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
        volumes: List[Dict[str, Any]],
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
        # This will largely be overridden by init containers.
        sec_ctx = V1PodSecurityContext(run_as_group=1000, run_as_user=1000)
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
                cmname, self.namespace
            )
        except ApiException as e:
            if e.status == 404:
                self.logger.debug(f"Configmap {cmname} already deleted")
            else:
                self.logger.exception("Exception deleting configmap")
                raise K8sApiException(e)
        else:
            self.logger.debug(f"Configmap {cmname} deleted: {status}")

    async def _pod_delete(self, username: str) -> None:
        """Delete the pod for the given username."""
        self.logger.info(f"Deleting pod for {username}")
        pname = _name_object(username, "pod")
        try:
            status = await self.v1.delete_namespaced_pod(pname, self.namespace)
        except ApiException as e:
            if e.status == 404:
                self.logger.debug(f"Pod {pname} already deleted")
            else:
                self.logger.exception("Exception deleting pod")
                raise K8sApiException(e)
        else:
            self.logger.debug(f"Pod {pname} deleted: {status}")
