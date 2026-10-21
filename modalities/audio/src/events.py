from __future__ import annotations

import asyncio
import json
import uuid
from collections import deque
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StreamEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int = 0
    type: str
    session_id: str
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    data: dict[str, Any] = Field(default_factory=dict)

    def as_sse(self, cursor: str | None = None) -> str:
        payload = self.model_dump(mode="json")
        data = json.dumps(payload, ensure_ascii=False)
        return f"id: {cursor or self.id}\nevent: {self.type}\ndata: {data}\n\n"


class EventBroker:
    """Small in-process fan-out broker with reconnect replay for the PoC."""

    def __init__(self, replay_size: int = 200) -> None:
        self.instance_id = uuid.uuid4().hex
        self._subscribers: set[asyncio.Queue[StreamEvent]] = set()
        self._history: deque[StreamEvent] = deque(maxlen=replay_size)
        self._next_id = 1
        self._lock = asyncio.Lock()

    def parse_cursor(self, cursor: str | None) -> int:
        if not cursor:
            return 0
        instance_id, separator, event_id = cursor.partition(":")
        if separator != ":" or instance_id != self.instance_id:
            return 0
        try:
            return max(0, int(event_id))
        except ValueError:
            return 0

    def cursor_for(self, event: StreamEvent) -> str:
        return f"{self.instance_id}:{event.id}"

    async def publish(self, event: StreamEvent) -> StreamEvent:
        async with self._lock:
            stored = event.model_copy(update={"id": self._next_id})
            self._next_id += 1
            self._history.append(stored)
            subscribers = tuple(self._subscribers)
        for subscriber in subscribers:
            if subscriber.full():
                subscriber.get_nowait()
            subscriber.put_nowait(stored)
        return stored

    async def subscribe(self, after_id: int = 0) -> AsyncIterator[StreamEvent]:
        queue: asyncio.Queue[StreamEvent] = asyncio.Queue(maxsize=100)
        async with self._lock:
            replay = [event for event in self._history if event.id > after_id]
            self._subscribers.add(queue)
        try:
            for event in replay:
                yield event
            while True:
                yield await queue.get()
        finally:
            async with self._lock:
                self._subscribers.discard(queue)
