"""Test fixtures."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import Mock, patch

import kubernetes_asyncio
import pytest
from asgi_lifespan import LifespanManager
from httpx import AsyncClient
from kubernetes_asyncio.client import ApiClient

import moneypenny.kubernetes
from moneypenny import main
from moneypenny.config import config
from moneypenny.models import Dossier, Group
from tests.support.constants import TEST_HOSTNAME
from tests.support.kubernetes import MockKubernetesApi

if TYPE_CHECKING:
    from typing import AsyncIterator, Iterator

    from fastapi import FastAPI


@pytest.fixture
async def app(
    mock_kubernetes: MockKubernetesApi, podinfo: Path
) -> AsyncIterator[FastAPI]:
    """Return a configured test application.

    Wraps the application in a lifespan manager so that startup and shutdown
    events are sent during test execution.
    """
    assets_path = Path(__file__).parent / "_assets"
    config.m_config_path = str(assets_path / "m.yaml")
    config.quips = str(assets_path / "quips.txt")
    config.moneypenny_timeout = 5
    async with LifespanManager(main.app):
        yield main.app


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """Return an ``httpx.AsyncClient`` configured to talk to the test app."""
    base_url = f"https://{TEST_HOSTNAME}/"
    async with AsyncClient(app=app, base_url=base_url) as client:
        yield client


@pytest.fixture
def dossier() -> Dossier:
    return Dossier(
        username="jb007",
        uid=1007,
        groups=[Group(name="doubleos", id=500), Group(name="staff", id=200)],
    )


@pytest.fixture
def podinfo(tmp_path: Path) -> Iterator[Path]:
    """Store some mock Kubernetes pod information and override config."""
    orig_podinfo_dir = config.podinfo_dir
    podinfo_dir = tmp_path / "podinfo"
    podinfo_dir.mkdir()
    (podinfo_dir / "name").write_text("moneypenny-78547dcf97-9xqq8")
    (podinfo_dir / "uid").write_text("00386592-214f-40c5-88e1-b9657d53a7c6")
    config.podinfo_dir = str(podinfo_dir)
    yield podinfo_dir
    config.podinfo_dir = orig_podinfo_dir


@pytest.fixture
def mock_kubernetes() -> Iterator[MockKubernetesApi]:
    """Replace the Kubernetes API with a mock class."""
    mock_api = MockKubernetesApi()
    with patch.object(moneypenny.kubernetes, "CoreV1Api") as mock_class:
        mock_class.return_value = mock_api
        with patch.object(moneypenny.kubernetes, "ApiClient") as mock_client:
            mock_client.return_value = Mock(spec=ApiClient)
            with patch.object(kubernetes_asyncio, "config") as mock_config:
                mock_config.load_incluster_config = Mock()
                yield mock_api
