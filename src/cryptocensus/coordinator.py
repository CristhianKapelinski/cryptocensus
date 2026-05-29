"""Coordinator: seed the task queue from a sample of image references."""

from __future__ import annotations

import logging

from .config import Settings, settings as default_settings
from .queue import TaskQueue

log = logging.getLogger("cryptocensus.coordinator")


def seed(references: list[str], s: Settings | None = None) -> int:
    s = s or default_settings
    queue = TaskQueue(s)
    count = queue.enqueue(references)
    log.info("seeded %d image references", count)
    return count
