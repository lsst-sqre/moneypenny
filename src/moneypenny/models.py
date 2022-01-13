"""Models for moneypenny."""

from typing import List

from pydantic import BaseModel, Field
from safir.metadata import Metadata as SafirMetadata

__all__ = ["Dossier", "Group", "Index", "AgentCache"]


AgentCache = dict[str, bool]


class Group(BaseModel):
    """A user group."""

    name: str = Field(..., title="Name of group", example="staff")

    id: int = Field(..., title="Numeric GID of group", ge=1, example=200)


class Dossier(BaseModel):
    """Request to Moneypenny to perform an action."""

    username: str = Field(..., title="User to act on", example="jb007")

    uid: int = Field(..., title="Numeric UID of user", ge=1, example=1007)

    groups: List[Group] = Field(..., title="Groups of user")


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
