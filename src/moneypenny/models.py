"""Models for moneypenny."""

from datetime import datetime
from enum import Enum
from typing import List

from pydantic import BaseModel, Field
from safir.metadata import Metadata as SafirMetadata

__all__ = [
    "Dossier",
    "Group",
    "Index",
    "Order",
    "Status",
    "UserStatus",
]


class Index(BaseModel):
    """Metadata returned by the external root URL of the application.

    Notes
    -----
    As written, this is not very useful. Add additional metadata that will be
    helpful for a user exploring the application, or replace this model with
    some other model that makes more sense to return from the application API
    root.
    """

    quip: str = Field(..., title="Queen and country, James")

    metadata: SafirMetadata = Field(..., title="Package metadata")


class Order(Enum):
    """Possible actions Moneypenny can take."""

    COMMISSION = "commission"
    RETIRE = "retire"


class Group(BaseModel):
    """A user group."""

    name: str = Field(..., title="Name of group", example="staff")

    id: int = Field(..., title="Numeric GID of group", ge=1, example=200)


class Dossier(BaseModel):
    """Request to Moneypenny to perform an action."""

    username: str = Field(..., title="User to act on", example="jb007")

    uid: int = Field(..., title="Numeric UID of user", ge=1, example=1007)

    groups: List[Group] = Field(..., title="Groups of user")


class Status(Enum):
    """Current commissioning status of a user."""

    COMMISSIONING = "commissioning"
    ACTIVE = "active"
    FAILED = "failed"
    RETIRING = "retiring"


class UserStatus(BaseModel):
    """Current commissioning status of a user."""

    username: str = Field(..., title="Username", example="jb007")

    status: Status = Field(..., title="Current status", example=Status.ACTIVE)

    last_changed: datetime = Field(
        ...,
        title="When the status last changed",
        example="2022-01-18T15:14:56Z",
    )

    uid: int = Field(
        ...,
        title="Numeric UID of user at last commissioning",
        ge=1,
        example=1007,
    )

    groups: List[Group] = Field(
        ..., title="Groups of user at last commissioning"
    )


class PodStatus(Enum):
    """Status of a pod.

    This is essentially the same as V1PodCondition, but isolated from the
    Kubernetes libraries.
    """

    PodScheduled = "PodScheduled"
    ContainersReady = "ContainersReady"
    Initialized = "Initialized"
    Ready = "Ready"
