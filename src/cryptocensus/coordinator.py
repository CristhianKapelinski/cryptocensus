"""Coordinator: seed the task queue from a sample of image references."""

from __future__ import annotations

import logging

from .config import Settings, settings as default_settings
from .queue import TaskQueue

log = logging.getLogger("cryptocensus.coordinator")


def seed(references: list[str], s: Settings | None = None, force: bool = False) -> int:
    """Enqueue references. By default skips references already processed (idempotent
    re-seeding); pass force=True to re-enqueue regardless (e.g. a full re-scan)."""
    s = s or default_settings
    queue = TaskQueue(s)
    count = queue.enqueue(references, skip_done=not force)
    log.info("seeded %d image references", count)
    return count
