"""Kubernetes client abstraction for Moneypenny."""
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog
from kubernetes.client import (
    V1Capabilities,
    V1ConfigMap,
    V1ConfigMapVolumeSource,
    V1Container,
    V1LocalObjectReference,
    V1ObjectMeta,
    V1Pod,
    V1PodSecurityContext,
    V1PodSpec,
    V1SecurityContext,
    V1Volume,
)
from kubernetes.client.api import core_v1_api
from kubernetes.client.exceptions import ApiException
from kubernetes.config import load_incluster_config, load_kube_config
from kubernetes.config.config_exception import ConfigException

from .config import Configuration
from .errors import K8sApiException, OperationFailed, PodNotFound

logger = structlog.get_logger(__name__)


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
    """

    def __init__(self, moneypenny) -> None:  # type: ignore
        """Create a new client for the cluster we are running in.
        We ignore type in order to prevent a circular dependency."""
        if not moneypenny:
            raise ValueError(
                "KubernetesClient must have an associated 'moneypenny'"
            )
        self.moneypenny = moneypenny
        self.config: Configuration = moneypenny.config
        namespace = "default"
        nsf = self.config.namespace_file
        try:
            namespace = Path(nsf).read_text().strip()
        except FileNotFoundError:
            logger.warn(f"Namespace file {nsf} not found; using 'default'")
        self.namespace = namespace
        try:
            load_incluster_config()
        except ConfigException:
            logger.warn("In-cluster config failed; trying kube_config.")
            load_kube_config()  # Crash and burn if this fails too.
        self.api = core_v1_api.CoreV1Api()

    def make_objects(
        self,
        username: str,
        volumes: List[Any],
        init_containers: List[Any],
        dossier: Dict[str, Any],
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
        init_containers: This is the list of initContainers to be run,
          in sequence.  The format is exactly what is deserialized with
          yaml.safe_load().
        dossier: This is a dictionary that has the format of a token
          returned by Gafaelfawr.
        pull_secret_name: name of the secret in the current namespace
          (if any) used to pull Docker images.
        """
        pod = self._make_pod(
            username=username,
            volumes=volumes,
            init_containers=init_containers,
            dossier=dossier,
            pull_secret_name=pull_secret_name,
        )
        dossier_cm = self._create_dossier_configmap(dossier)
        logger.info(f"Creating configmap for {username}")
        try:
            status = self.api.create_namespaced_config_map(
                self.namespace, dossier_cm
            )
        except ApiException as e:
            logger.exception("Exception creating configmap")
            raise K8sApiException(e)
        logger.debug(f"Configmap for {username} created: {status}")
        logger.info(f"Creating pod for {username}")
        try:
            status = self.api.create_namespaced_pod(self.namespace, pod)
        except ApiException as e:
            logger.exception("Exception creating pod")
            raise K8sApiException(e)
        logger.debug(f"Pod for {username} created: {status}")

    def delete_objects(self, username: str) -> None:
        """Delete both the pod and its associated configmap, given a
        username.

        Parameters
        ----------
        name: Username for the pod and configmap to delete.

        Raises
        ------
        K8sApiException if the deletion failed.
        """
        self._pod_delete(username)
        self._configmap_delete(username)

    def check_pod_completed(self, username: str) -> bool:
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
            pod = self.api.read_namespaced_pod(pname, self.namespace)
            status = pod.status
        except ApiException as exc:
            if exc.status == 404:
                raise PodNotFound(f"Pod {pname} not found")
            logger.exception("Error checking on pod completion")
            raise K8sApiException(exc)
        phase: str = status.phase
        if phase == "Succeeded":
            return True
        if phase == "Pending" or "Running":
            return False
        if phase == "Unknown":
            raise OperationFailed(f"Pod {pname} in Unknown phase")
        raise OperationFailed(status.message)

    def _make_pod(
        self,
        username: str,
        volumes: List[Any],
        init_containers: List[Any],
        dossier: Dict[str, Any],
        pull_secret_name: Optional[str] = None,
    ) -> V1Pod:
        spec = self._make_pod_spec(
            username=username,
            volumes=volumes,
            init_containers=init_containers,
            dossier=dossier,
            pull_secret_name=pull_secret_name,
        )
        pname = _name_object(username, "pod")
        md = V1ObjectMeta(name=pname)
        pod = V1Pod(metadata=md, spec=spec)
        return pod

    def _make_pod_spec(
        self,
        username: str,
        volumes: List[Any],
        init_containers: List[Any],
        dossier: Dict[str, Any],
        pull_secret_name: Optional[str] = None,
    ) -> V1PodSpec:
        """This is its own method for unit testing.  It just defines the
        in-memory K8s object corresponding to the Pod."""
        container = V1Container(
            name="null",
            image=self.config.null_container_image,
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

        self._add_dossier_vol(dossier, init_containers)
        username = dossier["token"]["data"]["uid"]
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
        pod_spec = V1PodSpec(
            automount_service_account_token=False,
            containers=[container],
            init_containers=init_containers,
            image_pull_secrets=pull_secret,
            # node_selector=labels,
            security_context=V1PodSecurityContext(
                run_as_non_root=True,
                run_as_group=1000,
                run_as_user=1000,
            ),
            restart_policy="OnFailure",
            volumes=volumes,
        )
        return pod_spec

    def _create_dossier_configmap(
        self, dossier: Dict[str, Any]
    ) -> V1ConfigMap:
        """Build the configmap containing the dossier that will be
        mounted to the working container.  Dossier will be in JSON
        format, purely because Python includes a json parser but not
        a yaml parser in its standard library.
        """
        uname = dossier["token"]["data"]["uid"]  # Fatal if key doesn't exist
        cmname = _name_object(uname, "cm")
        djson = json.dumps(dossier, sort_keys=True, indent=4)
        data = {"dossier.json": djson}
        cm = V1ConfigMap(metadata=V1ObjectMeta(name=cmname), data=data)
        return cm

    def _add_dossier_vol(
        self, dossier: Dict[str, Any], init_containers: List[Any]
    ) -> None:
        """Updates init_containers in place."""
        uname = dossier["token"]["data"]["uid"]
        vname = _name_object(f"dossier-{uname}", "vol")
        for ctr in init_containers:
            if not ctr.get("volumeMounts"):
                ctr["volumeMounts"] = []
            ctr["volumeMounts"].append(
                {
                    "name": vname,
                    "mountPath": self.config.dossier_path,
                    "readOnly": True,
                }
            )

    def _configmap_create(self, cm: V1ConfigMap) -> None:
        """Create the ConfigMap in the cluster."""
        try:
            status = self.api.create_namespaced_configmap(self.namespace, cm)
        except ApiException as e:
            if e.status != 409:
                estr = "Create configmap failed: {}".format(e)
                logger.exception(estr)
                raise K8sApiException(e)
            else:
                logger.info("Configmap already exists.")
        logger.debug(f"Configmap created: {status}")

    def _configmap_delete(self, username: str) -> None:
        """Delete the ConfigMap for the given name."""
        cmname = _name_object(username, "cm")
        try:
            status = self.api.delete_namespaced_config_map(
                name=cmname, namespace=self.namespace
            )
        except ApiException as e:
            logger.exception("Exception deleting configmap")
            raise K8sApiException(e)
        logger.debug(f"Configmap {cmname} deleted: {status}")

    def _pod_delete(self, username: str) -> None:
        """Delete the pod for the given username."""
        logger.info(f"Deleting pod for {username}")
        pname = _name_object(username, "pod")
        try:
            status = self.api.delete_namespaced_pod(pname, self.namespace)
        except ApiException as exc:
            logger.exception("Exception deleting pod")
            raise K8sApiException(exc)
        logger.debug(f"Pod {pname} deleted: {status}")
