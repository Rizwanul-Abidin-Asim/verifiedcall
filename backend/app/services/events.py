"""In-process fan-out so the dashboard can watch decisions arrive live.

Deliberately not Redis. A single API process serves the demo, and an asyncio queue per
subscriber has no infrastructure to fail on stage. The publish side is written so that a
slow or dead dashboard can never slow down, block, or fail a payment decision: queues are
bounded and a full queue drops the event rather than waiting.

If this ever runs on more than one worker, swap the broker for Redis pub/sub and keep
this interface.
"""

import asyncio
import contextlib
import logging
from collections.abc import Iterator

log = logging.getLogger("events")

QUEUE_DEPTH = 100


class EventBroker:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue] = set()

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    async def publish(self, event: dict) -> None:
        """Hand an event to every listener. Never raises, never blocks."""
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                log.warning("events.dropped subscriber queue full, depth=%d", QUEUE_DEPTH)
            except Exception as exc:  # noqa: BLE001 - a broken listener is not a payment failure
                log.warning("events.publish_failed %r", exc)

    @contextlib.contextmanager
    def subscribe(self) -> Iterator[asyncio.Queue]:
        """Register a listener for the life of the with-block."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_DEPTH)
        self._subscribers.add(queue)
        log.info("events.subscribed count=%d", len(self._subscribers))
        try:
            yield queue
        finally:
            self._subscribers.discard(queue)
            log.info("events.unsubscribed count=%d", len(self._subscribers))


broker = EventBroker()
