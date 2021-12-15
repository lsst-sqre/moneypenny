"""Configuration definition."""

__all__ = ["Configuration"]

import os
from dataclasses import dataclass


@dataclass
class Configuration:
    """Configuration for moneypenny."""

    name: str = os.getenv("SAFIR_NAME", "moneypenny")
    """The application's name, which doubles as the root HTTP endpoint path.

    Set with the ``SAFIR_NAME`` environment variable.
    """

    profile: str = os.getenv("SAFIR_PROFILE", "development")
    """Application run profile: "development" or "production".

    Set with the ``SAFIR_PROFILE`` environment variable.
    """

    logger_name: str = os.getenv("SAFIR_LOGGER", "moneypenny")
    """The root name of the application's logger.

    Set with the ``SAFIR_LOGGER`` environment variable.
    """

    log_level: str = os.getenv("SAFIR_LOG_LEVEL", "DEBUG")
    """The log level of the application's logger.

    Set with the ``SAFIR_LOG_LEVEL`` environment variable.
    """

    docker_secret_name: str = os.getenv("DOCKER_SECRET_NAME", "")
    """Name of the kubernetes secret to use to pull images.

    Set by the ``DOCKER_SECRET_NAME`` environment variable,
    configured by the helm chart.
    """

    dossier_path: str = os.getenv("MONEYPENNY_DOSSIER_FILE", "/opt/dossier")
    """Path to the dossier file's mountpoint created in the initContainers.
    Leave at default in normal operation.  Note that it does not contain the
    filename (usually "dossier.json")
    """

    config_dir: str = os.getenv(
        "MONEYPENNY_CONFIG_DIR", "/opt/lsst/software/moneypenny/config"
    )
    """Directory where the Moneypenny ConfigMaps will be mounted.  Leave
    at default in normal operation.
    """

    m_config_path: str = os.getenv(
        "MONEYPENNY_M_CONFIG_FILE", f"{config_dir}/M/m.yaml"
    )
    """Path to M's standing orders.  Leave at default in normal operation.
    """

    quips: str = os.getenv(
        "MONEYPENNY_QUIP_FILE", f"{config_dir}/quips/quips.txt"
    )
    """Path to Moneypenny's quip file.  Leave at default in normal operation.
    """

    podinfo_dir: str = os.getenv("MONEYPENNY_PODINFO_DIR", "/etc/podinfo")
    """Path at which Kubernetes has mounted the pod metadata files."""

    moneypenny_timeout: int = int(os.getenv("MONEYPENNY_TIMEOUT") or "300")
    """Timeout (in seconds) to wait for all containers in the action pod to
    complete.  Defaults to 300.
    """


config = Configuration()
"""Configuration for Moneypenny."""
