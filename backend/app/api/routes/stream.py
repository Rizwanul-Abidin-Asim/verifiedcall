"""Server-sent events for the live decision feed.

Three things this has to get right, all of which are about the demo not breaking:
- a client that closes its tab must not leak a subscriber, so the generator always exits
  through the context manager
- a quiet period must not look like a dropped connection, so we send a keepalive
- a client that stops reading must not back up memory, which the bounded queue in
  services/events.py handles by dropping rather than growing
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from app.services.events import broker

log = logging.getLogger("api.stream")
router = APIRouter(tags=["stream"])

KEEPALIVE_SECONDS = 15


async def decision_event_source(request: Request) -> AsyncIterator[dict]:
    """The feed itself, kept separate from the route so it can be tested directly."""
    with broker.subscribe() as queue:
        yield {"event": "connected", "data": json.dumps({"listening": True})}
        while True:
            if await request.is_disconnected():
                log.info("stream.client_disconnected")
                break
            try:
                event = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_SECONDS)
            except TimeoutError:
                # Nothing happened; prove the connection is still alive.
                yield {"event": "keepalive", "data": "{}"}
                continue
            yield {"event": "decision", "data": json.dumps(event)}


@router.get("/stream/decisions")
async def stream_decisions(request: Request) -> EventSourceResponse:
    return EventSourceResponse(decision_event_source(request))
