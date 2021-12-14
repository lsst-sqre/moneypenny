"""Handlers for the app's external root, ``/moneypenny/``."""

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Response,
)
from fastapi.responses import PlainTextResponse
from safir.metadata import get_metadata

from ..config import config
from ..dependencies import moneypenny_dependency
from ..exceptions import K8sApiException, PodNotFound
from ..models import Dossier, Index
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


@external_router.get(
    "/{username}",
    description=(
        "Because Moneypenny tidies up rather quickly, 200 and 202 are"
        " unlikely and 404 is common after successful execution."
    ),
    responses={
        200: {"description": "Pod for this user has run successfully"},
        202: {"description": "Pod for this user is currently running"},
        404: {"description": "No pod found for this user"},
    },
    response_class=PlainTextResponse,
    summary="Status for user",
)
async def get_user(
    username: str,
    response: Response,
    moneypenny: Moneypenny = Depends(moneypenny_dependency),
) -> str:
    try:
        completed = await moneypenny.check_completed(username)
        if completed:
            return f"Pod for {username} succeeded"
        else:
            response.status_code = 202
            return f"Pod for {username} is running"
    except PodNotFound as exc:
        response.status_code = 404
        return str(exc)
    except K8sApiException as exc:
        response.status_code = 500
        return str(exc)


async def _check_conflict(username: str, moneypenny: Moneypenny) -> None:
    """Check if processing is already in progress for this user.

    Raises
    ------
    fastapi.HTTPException
        Exception with a 409 error if processing is already in progress for
        this user.
    """
    try:
        completed = await moneypenny.check_completed(username)
        if not completed:
            msg = f"Orders for {username} are still in progress"
            raise HTTPException(status_code=409, detail=msg)
    except PodNotFound:
        pass


@external_router.post(
    "/commission",
    description="Perform provisioning steps with the details from the body",
    response_class=PlainTextResponse,
    responses={
        409: {"description": "Commissioning for user already in progress"},
    },
    status_code=202,
    summary="Provision user",
)
async def post_commission(
    commission: Dossier,
    background_tasks: BackgroundTasks,
    moneypenny: Moneypenny = Depends(moneypenny_dependency),
) -> str:
    await _check_conflict(commission.username, moneypenny)
    background_tasks.add_task(
        moneypenny.dispatch_order,
        action="commission",
        dossier=commission,
    )
    return f"Commissioning {commission.username}"


@external_router.post(
    "/retire",
    description="Perform deprovisioning steps with the details from the body",
    response_class=PlainTextResponse,
    responses={
        409: {"description": "Dossiering for user already in progress"},
    },
    status_code=202,
    summary="Deprovision user",
)
async def post_retire(
    commission: Dossier,
    background_tasks: BackgroundTasks,
    moneypenny: Moneypenny = Depends(moneypenny_dependency),
) -> str:
    await _check_conflict(commission.username, moneypenny)
    background_tasks.add_task(
        moneypenny.dispatch_order,
        action="retire",
        dossier=commission,
    )
    return f"Retiring {commission.username}"
