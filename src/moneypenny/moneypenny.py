"""Moneypenny is M's executive assistant."""

from __future__ import annotations

import asyncio
import random
from typing import TYPE_CHECKING

import yaml

from .config import config
from .exceptions import CatGotYourTongueError, NonsensicalOrderError
from .kubernetes import KubernetesClient
from .models import Dossier, Order, Status, UserStatus
from .state import State

if TYPE_CHECKING:
    from typing import Any, Dict, List, Optional

    from structlog.stdlib import BoundLogger

__all__ = ["Moneypenny"]


class Moneypenny:
    """Moneypenny provides the high-level interface for administrative
    tasks within the Kubernetes cluster."""

    def __init__(
        self,
        k8s_client: KubernetesClient,
        logger: BoundLogger,
        state: State,
    ) -> None:
        self.k8s_client = k8s_client
        self.logger = logger
        self.state = state

    def _read_quips(self) -> List[str]:
        """Read quips file.  This is in fortune format, which is to
        say, blocks of text separated by lines consisting only of '%'.

        Unlike classic fortune format, we will treat lines starting with
        '#' as comment lines.  We also throw away empty quips, so if your
        quipfile starts or ends with '%' it doesn't matter.
        """
        q_idx: int = 0
        quips: List[str] = [""]
        with open(config.quips, "r") as f:
            for line in f:
                if line.startswith("#"):
                    continue
                if line.rstrip() == "%":
                    quips.append("")
                    q_idx += 1
                    continue
                quips[q_idx] += line
        return quips

    def quip(self) -> str:
        """Return one of our quips at random."""
        # We reload quips each time; changing the configmap under a running
        #  instance is allowed.
        quips = self._read_quips()
        try:
            return random.choice(quips)
            # We need at least one quip in the list
        except IndexError:
            raise CatGotYourTongueError()

    def _read_order(self, order: Order) -> List[Dict[str, Any]]:
        """Read an order from M.  The order key corresponds to a route in
        handlers.external.  What is returned is a list of containers to
        be run in sequence for that order.
        """
        with open(config.m_config_path, "r") as f:
            orders = yaml.safe_load(f)
        try:
            return orders[order.value]
        except KeyError:
            raise NonsensicalOrderError()

    def _read_volumes(self) -> List[Dict[str, Any]]:
        with open(config.m_config_path, "r") as f:
            orders = yaml.safe_load(f)
        return orders.get("volumes", [])

    async def dispatch_order(self, order: Order, dossier: Dossier) -> bool:
        """Start processing an order.

        Carry out an order based on standing orders and the dossier
        supplied.  This amounts to asking our Kubernetes client to create
        a ConfigMap from the dossier, and then creating a pod with
        containers from the list of containers specified in the standing
        orders for the associated order, as well as the Volumes (if any)
        associated with the standing orders.

        This should be run by the scheduler, since awaiting it blocks until
        the order succeeds or fails.

        Parameters
        ----------
        order : `moneypenny.models.Order`
            The order to execute.
        dossier : `moneypenny.models.Dossier`
            Dossier associated with the order for the user.

        Returns
        -------
        container_started : `bool`
            Whether a container needed to be started for this order.  If this
            returns `False`, the order should be considered already
            complete.  This might be because the order is empty, or it might
            be because the order has already happened for this dossier and
            order.
        """
        username = dossier.username
        status = self.get_user_status(username)
        if (
            status
            and status.status == Status.ACTIVE
            and order == Order.COMMISSION
            and status.uid == dossier.uid
            and status.groups == dossier.groups
        ):
            msg = f"Skipping order {order.value} for {username}: no changes"
            self.logger.info(msg)
            return False

        self.logger.info(f"Submitting order {order.value} for {username}")
        if order == Order.COMMISSION:
            self.state.record_commission_start(dossier)
        elif order == Order.RETIRE:
            self.state.record_retire_start(dossier)

        volumes = self._read_volumes()
        containers = self._read_order(order)
        if not containers:
            self.logger.info("Empty order for {order.value}, nothing to do")
            if order == Order.COMMISSION:
                self.state.record_complete(dossier.username)
            elif order == Order.RETIRE:
                self.state.record_complete(dossier.username)
            return False

        await self.k8s_client.make_objects(
            username=username,
            containers=containers,
            volumes=volumes,
            dossier=dossier,
            pull_secret_name=config.docker_secret_name,
        )
        return True

    async def manage_order(self, order: Order, username: str) -> None:
        """Start a background task to wait for order completion.

        This is done instead of using FastAPI's ``BackgroundTasks`` directly
        because httpx's ``AsyncClient`` blocks return from a call to a test
        app until all background tasks have completed, which isn't the
        behavior we want to test.  This technique was taken from
        https://stackoverflow.com/questions/68542054/
        """
        loop = asyncio.get_event_loop()
        loop.create_task(self._manage_order(order, username))

    async def _manage_order(self, order: Order, username: str) -> None:
        """Wait for an order to complete.

        This is the internal implementation of `wait_for_order`.  Wait for a
        running pod for a given user to complete and then clean up the
        resources.

        Parameters
        ----------
        username : `str`
            The username whose pod we're waiting for.
        """
        self.logger.debug(
            f"Waiting for completion of order {order.value} for {username}"
        )
        timeout = config.moneypenny_timeout
        success = False
        try:
            await asyncio.wait_for(
                self.k8s_client.wait_for_pod(username), timeout
            )
        except asyncio.TimeoutError:
            msg = (
                f"Order {order.value} for {username} did not complete in"
                f" {timeout}s"
            )
            self.logger.error(msg)
        except Exception:
            self.logger.exception(f"Order {order.value} for {username} failed")
        else:
            success = True

        # Clean up the Kubernetes resources and log the result.
        completed_str = "completed" if success else "failed"
        msg = f"Order {order.value} {completed_str} for {username}: tidying up"
        self.logger.info(msg)
        try:
            await self.k8s_client.delete_objects(username)
        except Exception:
            msg = f"Failed to tidy up for {order.value} for {username}"
            self.logger.exception(msg)
        else:
            msg = (
                f"Tidied up after {order.value} for {username}; awaiting"
                " further instructions"
            )
            self.logger.info(msg)

        # Record the state change and log the timeout if relevant.
        if success:
            self.state.record_complete(username)
        else:
            self.state.record_failure(username)

    def get_user_status(self, username: str) -> Optional[UserStatus]:
        """Get the status of a user.

        Parameters
        ----------
        username : `str`
            Username of user.

        Returns
        -------
        status : `moneypenny.models.UserStatus` or `None`
            Status of the user if they are known, otherwise `None`.
        """
        return self.state.get_user_status(username)

    async def wait_for_order(self, username: str) -> None:
        """Wait for the pod for a user to finish running.

        Parameters
        ----------
        username : `str`
            The user whose pod to wait for.

        Raises
        ------
        KeyError
            No pod for this user was ever started.
        """
        await self.state.wait_for_completion(username)
