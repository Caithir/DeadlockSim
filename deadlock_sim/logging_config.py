"""Centralized logging configuration for DeadlockSim.

Call ``setup_logging()`` once at application startup (GUI, CLI, or MCP server).
Azure App Service captures stdout/stderr automatically, so a StreamHandler is
sufficient — no file handler needed.

Environment variables
---------------------
DEADLOCKSIM_LOG_LEVEL : str
    Override the root log level (default ``INFO``).  Set to ``DEBUG`` for
    verbose output during local development.
"""

from __future__ import annotations

import logging
import os
import sys

_CONFIGURED = False


def setup_logging() -> None:
    """Configure the root logger for DeadlockSim.

    Safe to call multiple times — only the first call has an effect.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return
    _CONFIGURED = True

    level_name = os.environ.get("DEADLOCKSIM_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger("deadlock_sim")
    root.setLevel(level)
    root.addHandler(handler)
    root.propagate = False
