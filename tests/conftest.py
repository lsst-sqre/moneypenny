import asyncio
import json
import os
from typing import Any, AsyncGenerator, Dict, Generator

import aiohttp
import pytest

import moneypenny

here = os.path.dirname(os.path.realpath(__file__))
assets = os.path.join(here, "_assets")


@pytest.fixture(scope="module")
def loop() -> Generator:
    loop = asyncio.get_event_loop()
    yield loop


@pytest.fixture(scope="module")
async def app(loop: asyncio.AbstractEventLoop) -> AsyncGenerator:
    m_app = moneypenny.create_app()
    runner = aiohttp.web.AppRunner(m_app)
    await runner.setup()
    site = aiohttp.web.TCPSite(runner, "127.0.0.1", 8080)
    await site.start()
    eve = m_app["moneypenny"]
    cfg = eve.config
    cfg.m_config_path = os.path.join(assets, "m.yaml")
    cfg.quips = os.path.join(assets, "quips.txt")
    yield m_app
    await site.stop()
    await runner.cleanup()


@pytest.fixture(scope="module")
def dossier() -> Dict[str, Any]:
    with open(os.path.join(assets, "dossier.json")) as f:
        return json.load(f)


@pytest.fixture(scope="module")
async def session(
    loop: asyncio.AbstractEventLoop, app: aiohttp.web.Application
) -> AsyncGenerator:
    ses = aiohttp.ClientSession()
    yield ses
    await ses.close()
