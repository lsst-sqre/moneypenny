"""Test functions for checking K8s objects.  We do not actually take any
actions in the cluster here; instead, we just check that the in-memory
objects are created correctly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import structlog

from moneypenny.moneypenny import Moneypenny

if TYPE_CHECKING:
    from fastapi import FastAPI


def test_read_quips(app: FastAPI) -> None:
    """Load quips, make sure we got a single item."""
    moneypenny = Moneypenny(MagicMock(), structlog.get_logger(__name__))
    quips = moneypenny._read_quips()
    assert len(quips) == 1


def test_quip(app: FastAPI) -> None:
    """The asset only has a single quip.  Make sure we got it."""
    moneypenny = Moneypenny(MagicMock(), structlog.get_logger(__name__))
    quip = moneypenny.quip().strip()
    assert quip == "Flattery will get you nowhere... but don't stop trying."


def test_read_orders(app: FastAPI) -> None:
    """Ensure we read the order file correctly."""
    moneypenny = Moneypenny(MagicMock(), structlog.get_logger(__name__))
    containers = moneypenny._read_order("commission")
    assert containers[0]["name"] == "farthing"


def test_read_volumes(app: FastAPI) -> None:
    """Ensure we read the (empty) volume list from the order file."""
    moneypenny = Moneypenny(MagicMock(), structlog.get_logger(__name__))
    volumes = moneypenny._read_volumes()
    assert volumes == [
        {
            "name": "homedirs",
            "nfs": {"path": "/homedirs", "server": "10.10.10.10"},
        }
    ]
