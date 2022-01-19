"""Test functions for checking K8s objects.  We do not actually take any
actions in the cluster here; instead, we just check that the in-memory
objects are created correctly.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import structlog
from fastapi import FastAPI

from moneypenny.models import Order
from moneypenny.moneypenny import Moneypenny
from moneypenny.state import State


@pytest.mark.asyncio
async def test_read_quips(app: FastAPI) -> None:
    """Load quips, make sure we got a single item."""
    logger = structlog.get_logger(__name__)
    moneypenny = Moneypenny(MagicMock(), logger, State())
    quips = moneypenny._read_quips()
    assert len(quips) == 1


@pytest.mark.asyncio
async def test_quip(app: FastAPI) -> None:
    """The asset only has a single quip.  Make sure we got it."""
    logger = structlog.get_logger(__name__)
    moneypenny = Moneypenny(MagicMock(), logger, State())
    quip = moneypenny.quip().strip()
    assert quip == "Flattery will get you nowhere... but don't stop trying."


@pytest.mark.asyncio
async def test_read_orders(app: FastAPI) -> None:
    """Ensure we read the order file correctly."""
    logger = structlog.get_logger(__name__)
    moneypenny = Moneypenny(MagicMock(), logger, State())
    containers = moneypenny._read_order(Order.COMMISSION)
    assert containers[0]["name"] == "farthing"


@pytest.mark.asyncio
async def test_read_volumes(app: FastAPI) -> None:
    """Ensure we read the (empty) volume list from the order file."""
    logger = structlog.get_logger(__name__)
    moneypenny = Moneypenny(MagicMock(), logger, State())
    volumes = moneypenny._read_volumes()
    assert volumes == [
        {
            "name": "homedirs",
            "nfs": {"path": "/homedirs", "server": "10.10.10.10"},
        }
    ]
