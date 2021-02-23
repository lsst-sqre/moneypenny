"""Moneypenny is M's executive assistant.
"""
__all__ = [
    "Moneypenny",
]

import asyncio
import datetime
import random
from math import log
from typing import Any, Dict, List, Optional

import structlog
import yaml
from aiohttp import web
from aiojobs import create_scheduler

from .config import Configuration
from .exceptions import (
    CatGotYourTongueError,
    NoMrBondIExpectYouToDie,
    NonsensicalOrderError,
)
from .kubernetes import KubernetesClient

logger = structlog.get_logger(__name__)


class Moneypenny:
    """Moneypenny provides the high-level interface for administrative
    tasks within the Kubernetes cluster."""

    async def init(self, app: web.Application) -> None:
        """Only called from the aiohttp startup hook.

        Parameters
        ----------
        app: unused.  Associated application instance.
        """

        self.config = Configuration()
        self.k8s_client = KubernetesClient(config=self.config)
        self._scheduler = await create_scheduler()

    async def cleanup(self, app: web.Application) -> None:
        """Clean up on exit.

        Called from the aiohttp server cleanup hook only.

        Note: By closing the scheduler, that will clean up all the
        jobs running inside of it.

        Parameters
        ----------
        app: unused.  Associated application instance."""
        await self._scheduler.close()

    async def _read_quips(self) -> List[str]:
        """Read quips file.  This is in fortune format, which is to
        say, blocks of text separated by lines consisting only of '%'.

        Unlike classic fortune format, we will treat lines starting with
        '#' as comment lines.  We also throw away empty quips, so if your
        quipfile starts or ends with '%' it doesn't matter.
        """
        q_idx: int = 0
        quips: List[str] = [""]
        with open(self.config.quips, "r") as f:
            for line in f:
                if line.startswith("#"):
                    continue
                if line.rstrip() == "%":
                    quips.append("")
                    q_idx += 1
                    continue
                quips[q_idx] += line
        return quips

    async def quip(self) -> str:
        """Return one of our quips at random."""
        # We reload quips each time; changing the configmap under a running
        #  instance is allowed.
        quips = await self._read_quips()
        try:
            return random.choice(quips)
            # We need at least one quip in the list
        except IndexError:
            raise CatGotYourTongueError()

    async def _read_order(self, order: str) -> List[Dict[str, Any]]:
        """Read an order from M.  The order key corresponds to a route in
        handlers.external.  What is returned is a list of containers to
        be run in sequence for that order.
        """
        with open(self.config.m_config_path, "r") as f:
            orders = yaml.safe_load(f)
        try:
            return orders[order]
        except KeyError:
            raise NonsensicalOrderError

    async def _read_volumes(self) -> List[Optional[Dict[str, Any]]]:
        vols: List[Optional[Dict[str, Any]]] = []
        try:
            vols = await self._read_order("volumes")  # type: ignore
        except NonsensicalOrderError:
            pass
        return vols

    async def dispatch_order(
        self, action: str, dossier: Dict[str, Any]
    ) -> None:
        """Hand a new order to the scheduler.  This lets us handle it
        asynchronously.
        """
        await self._scheduler.spawn(self.execute_order(action, dossier))

    async def execute_order(
        self, action: str, dossier: Dict[str, Any]
    ) -> None:
        """Carry out an order based on standing orders and the dossier
        supplied.  This amounts to asking our Kubernetes client to create
        a ConfigMap from the dossier, and then creating a pod with
        containers from the list of containers specified in the standing
        orders for the associated action, as well as the Volumes (if any)
        associated with the standing orders.

        This should be run by the scheduler, since awaiting it blocks until
        the order succeeds or fails.

        Parameters
        ----------
        action: The action to execute.
        dossier: Dossier associated with the order for the user.

        """
        username = dossier["username"]
        logger.info(f"Submitting order '{action}' for {username}")
        volumes = await self._read_volumes()
        containers = await self._read_order(action)
        if not containers:
            logger.warning("Empty order for {action}")
            return
        pull_secret_name = self.config.docker_secret_name
        self.k8s_client.make_objects(
            username=username,
            containers=containers,
            volumes=volumes,
            dossier=dossier,
            pull_secret_name=pull_secret_name,
        )
        tmout = self.config.moneypenny_timeout
        expiry = datetime.datetime.now() + datetime.timedelta(seconds=tmout)
        # Wait for order to complete
        logger.info(f"Awaiting completion for '{action}': {username}")
        count = 0
        while datetime.datetime.now() < expiry:
            count += 1
            logger.info(f"Checking on {username}: attempt #{count}")
            finito = await self.check_completed(username)
            if finito:
                logger.info(
                    f"Order '{action}' completed for {username}: "
                    + "tidying up."
                )
                self.k8s_client.delete_objects(username)
                logger.info(
                    f"Tidied up after '{action}' for {username};"
                    + " awaiting further instructions."
                )
                return
            # logarithmic backoff on wait
            await asyncio.sleep(int(log(count)))
        # Timed out
        estr = f"Pod '{action}' for {username} did not complete in {tmout}s"
        logger.exception(estr)
        logger.info(f"Attempting tidy-up for {username}.")
        self.k8s_client.delete_objects(username)
        raise NoMrBondIExpectYouToDie(estr)

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
        return self.k8s_client.check_pod_completed(username)
