"""Handlers for the app's external root, ``/moneypenny/``."""

import asyncio
from urllib.parse import urlparse

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Request,
    Response,
)
from fastapi.responses import RedirectResponse
from safir.metadata import get_metadata

from ..config import config
from ..dependencies import moneypenny_dependency
from ..models import Dossier, Index, Order, Status, UserStatus
from ..moneypenny import Moneypenny

__all__ = ["get_index", "external_router"]

external_router = APIRouter()
"""FastAPI router for all external handlers."""


@external_router.get(
    "/",
    description=("Returns metadata about Moneypenny."),
    response_model=Index,
    response_model_exclude_none=True,
    summary="Application metadata",
)
async def get_index(
    moneypenny: Moneypenny = Depends(moneypenny_dependency),
) -> Index:
    """GET ``/moneypenny/`` (the app's external root).

    Customize this handler to return whatever the top-level resource of your
    application should return. For example, consider listing key API URLs.
    When doing so, also change or customize the response model in
    `moneypenny.models.Index`.

    By convention, the root of the external API includes a field called
    ``metadata`` that provides the same Safir-generated metadata as the
    internal root endpoint.
    """
    metadata = get_metadata(
        package_name="moneypenny",
        application_name=config.name,
    )
    return Index(quip=moneypenny.quip().strip(), metadata=metadata)


def _url_for_get_user(request: Request, username: str) -> str:
    """Returns the URL for a user's status, fixing the scheme if needed."""
    url = request.url_for("get_user", username=username)
    if getattr(request.state, "forwarded_proto", None):
        proto = request.state.forwarded_proto
        return urlparse(url)._replace(scheme=proto).geturl()
    else:
        return url


@external_router.post(
    "/users",
    description="Commission a new user.",
    response_class=RedirectResponse,
    responses={
        303: {"description": "User commission started"},
        409: {"description": "Order for user still in progress"},
    },
    status_code=303,
    summary="Provision user",
)
async def commission_user(
    dossier: Dossier,
    request: Request,
    background_tasks: BackgroundTasks,
    moneypenny: Moneypenny = Depends(moneypenny_dependency),
) -> str:
    status = moneypenny.get_user_status(dossier.username)
    if status and status.status == Status.COMMISSIONING:
        if status.uid == dossier.uid and status.groups == dossier.groups:
            # Commissioning is in progress, but is doing the same thing that
            # was just requested, so we can redirect to the existing user
            # status URL.
            return _url_for_get_user(request, dossier.username)
    if status and status.status in (Status.COMMISSIONING, Status.RETIRING):
        msg = f"Orders for {dossier.username} are still in progress"
        raise HTTPException(status_code=409, detail=msg)

    created = await moneypenny.dispatch_order(Order.COMMISSION, dossier)
    if created:
        # A container was created, so we redirect to the status URL and start
        # a background task to wait for it to complete and then clean it up.
        background_tasks.add_task(
            moneypenny.manage_order,
            order=Order.COMMISSION,
            username=dossier.username,
        )

    # Redirect to the user's status page.
    return _url_for_get_user(request, dossier.username)


@external_router.get("/users/{username}", summary="Status for user")
async def get_user(
    username: str, moneypenny: Moneypenny = Depends(moneypenny_dependency)
) -> UserStatus:
    status = moneypenny.get_user_status(username)
    if status:
        return status
    else:
        raise HTTPException(status_code=404, detail="Unknown user")


@external_router.get(
    "/users/{username}/wait",
    response_class=RedirectResponse,
    summary="Wait for order",
)
async def wait_for_order(
    username: str,
    request: Request,
    moneypenny: Moneypenny = Depends(moneypenny_dependency),
) -> str:
    status = moneypenny.get_user_status(username)
    if not status:
        raise HTTPException(status_code=404, detail="Unknown user")
    if status.status == Status.ACTIVE:
        return _url_for_get_user(request, username)

    # An order is indeed in progress.  Wait for it to finish.
    try:
        timeout = config.moneypenny_timeout
        await asyncio.wait_for(moneypenny.wait_for_order(username), timeout)
        return _url_for_get_user(request, username)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=500, detail="Order timed out")


@external_router.post(
    "/users/{username}/retire",
    response_class=RedirectResponse,
    responses={
        204: {"description": "User retired"},
        303: {"description": "User retirement started"},
        409: {"description": "Order for user still in progress"},
    },
    status_code=303,
    summary="Retire user",
)
async def retire_user(
    username: str,
    dossier: Dossier,
    request: Request,
    background_tasks: BackgroundTasks,
    moneypenny: Moneypenny = Depends(moneypenny_dependency),
) -> Response:
    status = moneypenny.get_user_status(username)
    if status and status.status in (Status.COMMISSIONING, Status.RETIRING):
        msg = f"Orders for {username} are still in progress"
        raise HTTPException(status_code=409, detail=msg)

    created = await moneypenny.dispatch_order(Order.RETIRE, dossier)
    if not created:
        return Response(status_code=204)

    # A container was created, so we redirect to the status URL and start a
    # background task to wait for it to complete and then clean it up.
    background_tasks.add_task(
        moneypenny.manage_order, order=Order.RETIRE, username=username
    )

    # Redirect to the user's status page.
    redirect_url = _url_for_get_user(request, dossier.username)
    return RedirectResponse(redirect_url)
