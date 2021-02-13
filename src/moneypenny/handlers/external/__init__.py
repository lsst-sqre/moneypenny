"""Externally-accessible endpoint handlers that serve relative to
/moneypenny/.
"""

__all__ = [
    "quip",
    "commission_agent",
    "retire_agent",
]
from .agent import (
    quip,
    commission_agent,
    retire_agent,
)
