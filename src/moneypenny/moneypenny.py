"""Moneypenny is M's executive assistant.
"""
__all__ = [
    "Moneypenny",
]

import asyncio

from aiohttp import web
from aiojobs import create_scheduler
from aiojobs._job import Job

from typing import List, Dict, Any

import json
import random
import structlog

from .config import Configuration
from .kubernetes import KubernetesClient
from .singleton import Singleton
from .types import CatGotYourTongueError, NonsensicalOrderError

# These should be supplied as ConfigMaps
M="/opt/lsst/software/moneypenny/config/m.yaml"
QUIPS="/opt/lsst/software/moneypenny/config/quips.txt"

logger = structlog.get_logger(__name__)


class Moneypenny(metaclass=Singleton):
    """Moneypenny is unique.
    """

    async def init(self, app: web.Application) -> None:
        """Only called from the aiohttp startup hook.

        Parameters
        ----------
        app: unused.  Associated application instance.
        """
        
        self.k8s_client = KubernetesClient()
        self._scheduler = await create_scheduler()
        self.orders = {}
        self.quips = []
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

    async def _load_quips(self, quipfile:str = QUIPS) -> None:
        """Re-read quips file.  This is in fortune format, which is to
        say, blocks of text separated by lines consisting only of '%'.

        Unlike classic fortune format, we will treat lines starting with
        '#' as comment lines.  We also throw away empty quips, so if your
        quipfile starts or ends with '%' it doesn't matter.
        """
        quips = [""]
        q_idx = 0
        with open(quipfile,"r") as f:
            for l in f:
                if l.startswith("#"):
                    continue
                if l.rstrip() == '%':
                    q_idx += 1
                    quips[q_idx] = ""
                    continue
                quips[q_idx] += l
        self.quips = [ x for x in quips if x ]

    async def quip(self) -> str:
        """Return one of our quips at random.
        """
        # We reload quips each time; changing the configmap under a running
        #  instance is allowed.
        await self._load_quips()
        try:
            return random.choice(self.quips) # We need at least one quip
        except IndexError:
            raise CatGotYourTongueError()

    async def _read_orders(self, orderfile:str = M) -> None:
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
        """
        with open(orderfile, "r") as f:
            self.orders = yaml.safe_load(f)

    async def execute_order(self, verb: str, dossier: Dict[str,Any]) -> None:
        """Carry out an order based on standing orders and the dossier
        supplied.


        Parameters
        ----------
        verb: HTTP verb associated with the order.
        dossier: Dossier associated with the order for the user.

        """
        verb=verb.strip().lower()
        # We re-read the orders each time; the config map is allowed to change
        await self._read_orders()
        init_containers = self.orders.get(verb)
        if init_containers is None:
            raise NonsensicalOrderError(f"No orders for verb '{verb}'")
        await self.k8s_client.make_pod(init_containers=init_containers,
                                       dossier=dossier)

    async def check_completed(self, username: str) -> Bool:
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
        return await self.k8s_client.pod_completed(username)

    async def dump(self) -> str:
        repr = { "orders": self.orders,
                 "quips": self.quips }
        return json.dumps(repr, sort_keys=True, indent=4)
