"""Handlers for Moneypenny's external root, /moneypenny/."""

__all__ = [
    "quip",
    "commission_agent",
    "retire_agent",
]

import json
from importlib import resources
from typing import Any, Dict

from aiohttp import web
from jsonschema import validate

from ...exceptions import K8sApiException, PodNotFound
from .. import routes


@routes.get("/")
async def quip(request: web.Request) -> web.Response:
    """GET /moneypenny/

    Reply with a quip from Moneypenny (or a short conversational snippet)

    Returns a 200 response with the associated text being the quip.
    """
    moneypenny = request.config_dict["moneypenny"]
    quip = await moneypenny.quip()
    return web.HTTPOk(text=quip)


@routes.get("/{username}")
async def check_status(request: web.Request) -> web.Response:
    """GET /moneypenny/{username}

    Returns a 200 response if the username pod has run successfully,
     a 202 response if it is still in progress, and raises an error otherwise.
    If the pod cannot be found, a 404 is raised; otherwise a 500 with
     descriptive text is raised.

    Because Moneypenny tidies up rather quickly, a 200 is very unlikely,
     a 202 fairly unlikely, and a 404 common.
    """
    username = request.match_info["username"]
    moneypenny = request.config_dict["moneypenny"]
    try:
        completed = await moneypenny.check_completed(username)
        if completed:
            return web.HTTPOk(text=f"Pod for {username} succeeded")
        return web.HTTPAccepted(text=f"Pod for {username} is running")
    except PodNotFound as exc:
        raise web.HTTPNotFound(text=str(exc))
    except K8sApiException as exc:
        raise web.HTTPInternalServerError(text=str(exc))


async def _validate_post(request: web.Request) -> Dict[str, Any]:
    """Validates the POST body against the schema in post.json,
    and ensures that there is only one request in flight for a given
    user at any time.

    Returns the dict corresponding to the json body of the post if
    the post is acceptable according to the schema and if there is not
    already a request in processing state for the specified user.

    Raises a 409 Conflict if there is already a request in flight.
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
    try:
        completed = await moneypenny.check_completed(username)
        if not completed:
            raise web.HTTPConflict(
                text=f"Orders for {username} are still" + " in-process"
            )
    except PodNotFound:
        pass
    return body


@routes.post("/commission")
async def commission_agent(request: web.Request) -> web.Response:
    """POST /moneypenny/commission

    Perform provisioning steps with the details from the body.
    Schema for the body is validated against the post.json file.

    Returns 202 Accepted once the request has been submitted.
    """
    body = await _validate_post(request)
    moneypenny = request.config_dict["moneypenny"]
    username = body["username"]

    await moneypenny.dispatch_order(action="commission", dossier=body)
    return web.HTTPAccepted(text=f"Commissioning {username}")


@routes.post("/retire")
async def retire_agent(request: web.Request) -> web.Response:
    """POST /moneypenny/retire

    Perform deprovisioning steps with the details from the body.
    Schema for the body is validated against the post.json file.

    Returns 202 Accepted once the request has been submitted.

    Raises a 409 Conflict if there is already a request in flight.
    """
    body = await _validate_post(request)
    moneypenny = request.config_dict["moneypenny"]
    username = body["username"]

    await moneypenny.dispatch_order(action="retire", dossier=body)
    return web.HTTPAccepted(text=f"Retiring {username}")
