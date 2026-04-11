"""Local offline event queue for when the API is unreachable."""

import json
import logging
from pathlib import Path

logger = logging.getLogger("sentinel.queue")

MAX_QUEUE_SIZE = 500


class EventQueue:
    """File-backed FIFO queue for deploy events that failed to send.

    Events are stored as a JSON array in the queue file. The queue
    is capped at MAX_QUEUE_SIZE entries; oldest are dropped when full.
    """

    def __init__(self, queue_file: str):
        self.queue_file = Path(queue_file)
        self._events: list[dict] = []
        self._load()

    def _load(self) -> None:
        if not self.queue_file.exists():
            self._events = []
            return

        try:
            with open(self.queue_file, "r") as f:
                data = json.load(f)
            if isinstance(data, list):
                self._events = data
            else:
                logger.warning("Queue file has unexpected format, resetting")
                self._events = []
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load queue file, resetting: %s", e)
            self._events = []

    def _save(self) -> None:
        try:
            self.queue_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.queue_file.with_suffix(".tmp")
            with open(tmp, "w") as f:
                json.dump(self._events, f)
            tmp.replace(self.queue_file)
        except OSError as e:
            logger.error("Failed to save queue file: %s", e)

    def enqueue(self, event: dict) -> None:
        """Add an event to the queue. Drops oldest if at capacity."""
        self._events.append(event)
        if len(self._events) > MAX_QUEUE_SIZE:
            dropped = len(self._events) - MAX_QUEUE_SIZE
            self._events = self._events[dropped:]
            logger.warning("Queue full, dropped %d oldest events", dropped)
        self._save()

    def peek_all(self) -> list[dict]:
        """Return all queued events without removing them."""
        return list(self._events)

    def drop_first(self, count: int) -> None:
        """Remove the first `count` events from the queue."""
        self._events = self._events[count:]
        self._save()

    def size(self) -> int:
        return len(self._events)

    def is_empty(self) -> bool:
        return len(self._events) == 0
