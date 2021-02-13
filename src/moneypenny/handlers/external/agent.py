"""Handlers for Moneypenny's external root, /moneypenny/."""

__all__ = [
    "quip",
    "commission_agent",
    "retire_agent",
]

import json
from importlib import resources
from typing import List

from aiohttp import web
from jsonschema import validate

from ..moneypenny import Moneypenny
from ..handlers import routes
from ..types import PodNotFound, APIException

@routes.get("/")
async def quip(request: web.Request) -> web.Response:
    """GET /moneypenny

    Reply with a quip from Moneypenny (or a short conversational snippet)

    Returns a 200 response with the associated text being the quip.
    """
    moneypenny = request.config_dict["moneypenny"]
    return web.HTTPOk(text=moneypenny.quip())

@routes.get("/{username}")
async def check_status(request: web.Request) -> web.Response:
    """GET /moneypenny/{username}

    Returns a 200 response if the username pod has run successfully,
     a 202 response if it is still in progress, and raises an error otherwise.
    If the pod cannot be found, a 404 is raised; otherwise a 500 with
     descriptive text is raised.
    """
    name = request.match_info["username"]
    moneypenny = request.config_dict["moneypenny"]
    try:
        completed = await moneypenny.check_completed(username)
        if completed:
            return web.HTTPOk(text="Succeeded")
        return web.HTTPAccepted(text="Running")
    except PodNotFound as exc:
        raise web.HTTPNotFound(text=str(exc))
    except K8sApiException as exc:
        raise web.HTTPInternalServerError(text=str(exc))
    

@routes.post("/")
async def commission_agent(request: web.Request) -> web.Response:
    """POST /moneypenny

    Perform provisioning steps with the details from the body.
    Schema for the body is validated against the post.json file.

    Returns 202 Accepted once the request has been submitted.
    """
    body = await request.json()

    validate(
        instance=body,
        schema=json.loads(
            resources.read_text("moneypenny.schemas", "post.json")
        ),
    )
    moneypenny = request.config_dict["moneypenny"]
    username = body["username"]
    await moneypenny.execute_order(verb="post", dossier=body)
    return web.HTTPAccepted(text=f"Commissioning {username}")



@routes.delete("/{username}")
async def retire_agent(request: web.Request) -> web.Response:
    """DELETE /moneypenny/{username}

    Perform deprovisioning steps for the given username.  Returns a 202 once
    the request has been accepted.
    """
    name = request.match_info["username"]
    moneypenny = request.config_dict["moneypenny"]
    await moneypenny.execute_order(verb="delete", dossier={ "username": name })
    return web.HTTPAccepted(text=f"Retiring {username}")
