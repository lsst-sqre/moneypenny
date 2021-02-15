"""Moneypenny is M's executive assistant.
"""
__all__ = [
    "Moneypenny",
]

import asyncio
import datetime
import json
import random
from typing import Any, Dict, List

import structlog
import yaml
from aiohttp import web
from aiojobs import create_scheduler

from .config import Configuration
from .errors import (
    CatGotYourTongueError,
    NoMrBondIExpectYouToDie,
    NonsensicalOrderError,
)
from .kubernetes import KubernetesClient
from .singleton import Singleton

logger = structlog.get_logger(__name__)


class Moneypenny(metaclass=Singleton):
    """Moneypenny is unique."""

    async def init(self, app: web.Application) -> None:
        """Only called from the aiohttp startup hook.

        Parameters
        ----------
        app: unused.  Associated application instance.
        """

        self.config = Configuration()
        self.k8s_client = KubernetesClient(moneypenny=self)
        self._scheduler = await create_scheduler()
        self.orders: Dict[str, Any] = {}
        self.quips = List[str]
        await self._read_orders()
        await self._load_quips()

    async def cleanup(self, app: web.Application) -> None:
        """Clean up on exit.

        Called from the aiohttp server cleanup hook only.

        Note: By closing the scheduler, that will clean up all the
        jobs running inside of it.

        Parameters
        ----------
        app: unused.  Associated application instance."""
        await self._scheduler.close()

    async def _load_quips(self) -> None:
        """Re-read quips file.  This is in fortune format, which is to
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
        self.quips = [x for x in quips if x]  # type: ignore

    async def quip(self) -> str:
        """Return one of our quips at random."""
        # We reload quips each time; changing the configmap under a running
        #  instance is allowed.
        await self._load_quips()
        try:
            return random.choice(self.quips)  # type: ignore
            # We need at least one quip
        except IndexError:
            raise CatGotYourTongueError()

    async def _read_orders(self) -> None:
        """Read orders from M.  The orders will be in YAML, in the form of a
        dict, where the key is a string corresponding to the HTTP
        verb, lowercased.  Initially, this is only "post", although we
        expect "delete" to follow shortly.

        The value of each key is a list of initContainers; in the
        order document, this is exactly the yaml you would find in the
        K8s Container definition.  It will be stored into self.orders
        as the dict that yaml.safe_load() yields.

        This is then used to drive the construction of the Pod that is run
        when the order is executed--the initContainers will be run in
        sequence, with whatever securityContexts are specified in their
        YAML.

        There may be an additional key, "volumes".  This will be an optional
        list of volumes to be mounted to the container.  In the common case,
        this will be a one-item list specifying the read-write volume
        containing user homedirs.
        """
        with open(self.config.M, "r") as f:
            self.orders = yaml.safe_load(f)

    async def execute_order(self, verb: str, dossier: Dict[str, Any]) -> None:
        """Carry out an order based on standing orders and the dossier
        supplied.  This amounts to asking our Kubernetes client to create
        a ConfigMap from the dossier, and then creating a pod with
        initContainers from the initContainers specified in the standing
        orders for the associated verb, as well as the Volumes (if any)
        associated with the standing orders.


        Parameters
        ----------
        verb: HTTP verb associated with the order.
        dossier: Dossier associated with the order for the user.

        """
        verb = verb.strip().lower()
        # We re-read the orders each time; the config map is allowed to change
        await self._read_orders()
        init_containers = self.orders.get(verb)
        volumes = self.orders.get("volumes")
        if init_containers is None:
            raise NonsensicalOrderError(f"No orders for verb '{verb}'")
        if volumes is None:
            volumes = []
        username = dossier["token"]["data"]["uid"]
        logger.info(f"Submitting order '{verb}' for {username}")
        pull_secret_name = self.config.docker_secret_name
        self.k8s_client.make_objects(
            username=username,
            init_containers=init_containers,
            volumes=volumes,
            dossier=dossier,
            pull_secret_name=pull_secret_name,
        )
        tmout = self.config.moneypenny_timeout
        expiry = datetime.datetime.now() + datetime.timedelta(seconds=tmout)
        # Wait for order to complete
        logger.info(f"Awaiting completion for '{verb}': {username}")
        count = 0
        while True:
            count += 1
            logger.info(f"Checking on {username}: attempt #{count}")
            finito = await self.check_completed(username)
            if finito:
                break
            if datetime.datetime.now() > expiry:
                estr = f"Pod for {username} did not complete in {tmout}s"
                logger.exception(estr)
                logger.info(f"Attempting tidy-up for {username}.")
                self.k8s_client.delete_objects(username)
                raise NoMrBondIExpectYouToDie(estr)
            await asyncio.sleep(1)
        logger.info(f"Order '{verb}' completed for {username}: tidying up.")
        self.k8s_client.delete_objects(username)
        logger.info(
            f"Tidied up after '{verb}' for {username};"
            + " awaiting further instructions."
        )

    async def check_completed(self, username: str) -> bool:
        """Check on the completion status of an order's execution.

        Parameters
        ----------
        verb: HTTP verb associated with the order.
        dossier: Dossier associated with the order for the user.

        Returns
        -------
        True if the pod completed successfully, False if it has not completed.

        Raises
        ------
        PodNotFound if the pod cannot be found at all,
        ApiException if there was some other error

        """
        return self.k8s_client.check_pod_completed(username)

    async def dump(self) -> str:
        repr = {"orders": self.orders, "quips": self.quips}
        return json.dumps(repr, sort_keys=True, indent=4)
