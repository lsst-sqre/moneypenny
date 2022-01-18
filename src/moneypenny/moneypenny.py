"""Moneypenny is M's executive assistant."""

from __future__ import annotations

import asyncio
import datetime
import random
from math import log
from typing import TYPE_CHECKING

import yaml

from .config import config
from .exceptions import (
    CatGotYourTongueError,
    NoMrBondIExpectYouToDie,
    NonsensicalOrderError,
)
from .kubernetes import KubernetesClient
from .models import AgentCache, Dossier

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
        cache: AgentCache,
    ) -> None:
        self.k8s_client = k8s_client
        self.logger = logger
        self.cache = cache

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

    def _read_order(self, order: str) -> List[Dict[str, Any]]:
        """Read an order from M.  The order key corresponds to a route in
        handlers.external.  What is returned is a list of containers to
        be run in sequence for that order.
        """
        with open(config.m_config_path, "r") as f:
            orders = yaml.safe_load(f)
        try:
            return orders[order]
        except KeyError:
            raise NonsensicalOrderError()

    def _read_volumes(self) -> List[Optional[Dict[str, Any]]]:
        vols: List[Optional[Dict[str, Any]]] = []
        try:
            vols = self._read_order("volumes")  # type: ignore
        except NonsensicalOrderError:
            pass
        return vols

    async def dispatch_order(self, action: str, dossier: Dossier) -> bool:
        """Start processing an order.

        Carry out an order based on standing orders and the dossier
        supplied.  This amounts to asking our Kubernetes client to create
        a ConfigMap from the dossier, and then creating a pod with
        containers from the list of containers specified in the standing
        orders for the associated action, as well as the Volumes (if any)
        associated with the standing orders.

        This should be run by the scheduler, since awaiting it blocks until
        the order succeeds or fails.

        Parameters
        ----------
        action : `str`
            The action to execute.
        dossier : `moneypenny.models.Dossier`
            Dossier associated with the order for the user.

        Returns
        -------
        container_started : `bool`
            Whether a container needed to be started for this order.  If this
            returns `False`, the action should be considered already
            complete.  This might be because the order is empty, or it might
            be because the order has already happened for this dossier and
            action.
        """
        username = dossier.username
        cache_key = f"{action}:{dossier}"
        if self.cache.get(cache_key, None):
            return False
        self.logger.info(f"Submitting order '{action}' for {username}")
        volumes = self._read_volumes()
        containers = self._read_order(action)
        if not containers:
            self.logger.info("Empty order for {action}, nothing to do")
            # "No action" counts as successful.
            self.cache[cache_key] = True
            return False

        await self.k8s_client.make_objects(
            username=username,
            containers=containers,
            volumes=volumes,
            dossier=dossier,
            pull_secret_name=config.docker_secret_name,
        )
        return True

    async def wait_for_order(self, action: str, dossier: Dossier) -> None:
        """Start a background task to wait for order completion.

        This is done instead of using FastAPI's ``BackgroundTasks`` directly
        because httpx's ``AsyncClient`` blocks return from a call to a test
        app until all background tasks have completed, which isn't the
        behavior we want to test.  This technique was taken from
        https://stackoverflow.com/questions/68542054/
        """
        loop = asyncio.get_event_loop()
        loop.create_task(self._wait_for_order(action, dossier))

    async def _wait_for_order(self, action: str, dossier: Dossier) -> None:
        """Wait for an order to complete.

        This is the internal implementation of `wait_for_order`.  Wait for a
        running pod for a given user to complete and then clean up the
        resources.

        Parameters
        ----------
        action : `str`
            The action in progress, for logging.
        username : `str`
            The username whose pod we're waiting for.
        """
        tmout = config.moneypenny_timeout
        username = dossier.username
        cache_key = f"{action}:{dossier}"
        expiry = datetime.datetime.now() + datetime.timedelta(seconds=tmout)
        self.logger.info(f"Awaiting completion for '{action}': {username}")

        count = 0
        while datetime.datetime.now() < expiry:
            count += 1
            completed_str = "completed"
            self.logger.info(f"Checking on {username}: attempt #{count}")
            try:
                finito = await self.check_completed(username)
                if finito:
                    # Only set cache on successful completion
                    self.cache[cache_key] = True
            except Exception as exc:
                self.logger.error(f"{action}: {username} failed: {exc}")
                completed_str = "failed"
                finito = True
            if finito:
                self.logger.info(
                    f"Order '{action}' {completed_str} for {username}:"
                    " tidying up"
                )
                await self.k8s_client.delete_objects(username)
                self.logger.info(
                    f"Tidied up after '{action}' for {username};"
                    " awaiting further instructions"
                )
                return

            # logarithmic backoff on wait
            await asyncio.sleep(int(log(count)))

        # Timed out
        msg = f"Pod '{action}' for {username} did not complete in {tmout}s"
        self.logger.error(msg)
        self.logger.info(f"Attempting tidy-up for {username}")
        await self.k8s_client.delete_objects(username)
        raise NoMrBondIExpectYouToDie(msg)

    async def check_completed(self, username: str) -> bool:
        """Check on the completion status of an order's execution.

        Parameters
        ----------
        username: name of user to check on

        Returns
        -------
        True if the pod completed successfully, False if it has not completed.

        Raises
        ------
        PodNotFound if the pod cannot be found at all,
        ApiException if there was some other error

        """
        return await self.k8s_client.check_pod_completed(username)
