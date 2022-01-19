"""User state management."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Optional

from .models import Dossier, Status, UserStatus


class State:
    """Holds the state of users that have been seen by Moneypenny.

    Once a user has been commissioned with a given dossier, subsequent
    commissioning operations should be immediately successful unless any of
    the dossier information changed.  If the commissioning pod is still
    running, Moneypenny also needs to report the in-progress status.

    This class holds the state information to support those operations and
    provides methods to update the state.  This class does not do any of the
    work, only handles the state tracking.  Retired users are treated the same
    as unknown users.

    Notes
    -----
    This class doesn't do any locking since it assumes that it is called in an
    async framework and thus no locking is required as long as control isn't
    yielded with await.

    The state is stored in memory and is therefore per-process, which means
    that some duplicate work may happen if more than one Moneypenny process is
    running.  Commissioning and retiring should be idempotent, so this should
    only be the loss of a performance optimization.
    """

    def __init__(self) -> None:
        self._user_status: Dict[str, UserStatus] = {}

    def get_user_status(self, username: str) -> Optional[UserStatus]:
        """Get status for a user.

        Parameters
        ----------
        username : `str`
            Username of user.

        Returns
        -------
        status : `moneypenny.models.UserStatus` or `None`
            Status of the user if they are known, otherwise `None`.
        """
        return self._user_status.get(username)

    def record_commission_start(self, dossier: Dossier) -> None:
        """Record start of commissioning of a new user.

        Parameters
        ----------
        dossier : `moneypenny.models.Dossier`
            The details of the user being commissioned.
        """
        status = UserStatus(
            username=dossier.username,
            status=Status.COMMISSIONING,
            last_changed=datetime.now(tz=timezone.utc),
            uid=dossier.uid,
            groups=dossier.groups,
        )
        self._user_status[dossier.username] = status

    def record_retire_start(self, dossier: Dossier) -> None:
        """Record start of retiring a user.

        Parameters
        ----------
        dossier : `moneypenny.models.Dossier`
            The details of the user retiring.
        """
        status = UserStatus(
            username=dossier.username,
            status=Status.RETIRING,
            last_changed=datetime.now(tz=timezone.utc),
            uid=dossier.uid,
            groups=dossier.groups,
        )
        self._user_status[dossier.username] = status

    def record_complete(self, username: str) -> None:
        """Record completion of commissioning or retiring of a user.

        Parameters
        ----------
        username : `str`
            The user who retired.

        Raises
        ------
        KeyError
            The user's status was not found (retiring was never started).
        ValueError
            The user's status was in an invalid state, indicating that
            something has gone wrong internally with the ordering of
            operations.
        """
        user_status = self._user_status[username]
        if user_status.status not in (Status.COMMISSIONING, Status.RETIRING):
            msg = f"No action apparently in progress for {username}"
            raise ValueError(msg)
        if user_status.status == Status.COMMISSIONING:
            user_status.status = Status.ACTIVE
        else:
            del self._user_status[username]

    def record_failure(self, username: str) -> None:
        """Record failure of commissioning or retiring a user.

        A failed retirement just puts the user back into the active state.

        Parameters
        ----------
        username : `str`
            The user who failed to be commissioned or retired.

        Raises
        ------
        KeyError
            The user's status was not found (retiring was never started).
        ValueError
            The user's status was in an invalid state, indicating that
            something has gone wrong internally with the ordering of
            operations.
        """
        user_status = self._user_status[username]
        if user_status.status not in (Status.COMMISSIONING, Status.RETIRING):
            msg = f"No action apparently in progress for {username}"
            raise ValueError(msg)
        if user_status.status == Status.COMMISSIONING:
            user_status.status = Status.FAILED
        else:
            user_status.status = Status.ACTIVE
        user_status.last_changed = datetime.now(tz=timezone.utc)
