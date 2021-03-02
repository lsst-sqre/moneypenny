"""Test functions for checking K8s objects.  We do not actually take any
actions in the cluster here; instead, we just check that the in-memory
objects are created correctly.
"""

from aiohttp import web


async def test_read_quips(app: web.Application) -> None:
    """
    Load quips, make sure we got a single item.
    """
    eve = app["moneypenny"]
    quips = await eve._read_quips()
    assert len(quips) == 1


async def test_quip(app: web.Application) -> None:
    """
    The asset only has a single quip.  Make sure we got it.
    """
    eve = app["moneypenny"]
    quip = await eve.quip()
    assert quip.strip() == (
        "Flattery will get you nowhere... but don't stop trying."
    )


async def test_read_orders(app: web.Application) -> None:
    """
    Ensure we read the order file correctly.
    """
    eve = app["moneypenny"]
    containers = await eve._read_order("commission")
    assert containers[0]["name"] == "farthing"


async def test_read_volumes(app: web.Application) -> None:
    """
    Ensure we read the (empty) volume list from the order file.
    """
    eve = app["moneypenny"]
    volumes = await eve._read_volumes()
    assert not volumes and volumes is not None
