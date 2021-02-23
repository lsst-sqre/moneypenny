import asyncio
import datetime
from math import log
from typing import Any, Dict

import aiohttp

endpoint = "http://127.0.0.1:8080/moneypenny/"


async def test_route_get(session: aiohttp.ClientSession) -> None:
    response = await session.get(endpoint)
    assert response.status == 200
    txt = await response.text()
    assert txt.strip() == (
        "Flattery will get you nowhere... but don't stop trying."
    )


async def test_route_commission(
    session: aiohttp.ClientSession, dossier: Dict[str, Any]
) -> None:
    com_ep = f"{endpoint}commission"
    await _test_post(endpoint=com_ep, dossier=dossier, session=session)


async def test_route_retire(
    session: aiohttp.ClientSession, dossier: Dict[str, Any]
) -> None:
    ret_ep = f"{endpoint}retire"
    await _test_post(endpoint=ret_ep, dossier=dossier, session=session)


async def test_simultaneous_orders(
    session: aiohttp.ClientSession, dossier: Dict[str, Any]
) -> None:
    com_ep = f"{endpoint}commission"
    await session.post(com_ep, json=dossier)
    response = await session.post(com_ep, json=dossier)
    assert response.status == 409  # Should have caused a Conflict
    await _wait_until_clean(session, dossier)


async def _test_post(
    endpoint: str, dossier: Dict[str, Any], session: aiohttp.ClientSession
) -> None:
    username = dossier["username"]
    response = await session.post(endpoint, json=dossier)
    assert response.status == 202
    status_ep = f"{endpoint}{username}"
    response = await session.get(status_ep)
    assert response.status == 200 or 202  # Shouldn't have had time to run yet.
    await _wait_until_clean(session, dossier)


async def _wait_until_clean(
    session: aiohttp.ClientSession, dossier: Dict[str, Any]
) -> None:
    timeout = 60  # should be plenty of time
    username = dossier["username"]
    status_ep = f"{endpoint}{username}"
    count = 0
    expiry = datetime.datetime.now() + datetime.timedelta(seconds=timeout)
    while datetime.datetime.now() < expiry:
        response = await session.get(status_ep)
        if response.status == 404:
            # It cleaned up, all is well.
            return
        count += 1
        await asyncio.sleep(int(log(count)))
    assert False, f"Query to '{endpoint}' did not complete in {timeout}s!"
