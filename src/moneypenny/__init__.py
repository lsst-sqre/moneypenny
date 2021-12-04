"""The Moneypenny service."""

from importlib.metadata import PackageNotFoundError, version

from .config import Configuration
from .kubernetes import KubernetesClient
from .moneypenny import Moneypenny

__all__ = [
    "__version__",
    "Moneypenny",
    "Configuration",
    "KubernetesClient",
    "create_app",
]

__version__: str
"""The application version string (PEP 440 / SemVer compatible)."""

try:
    __version__ = version(__name__)
except PackageNotFoundError:
    # package is not installed
    __version__ = "0.0.0"
