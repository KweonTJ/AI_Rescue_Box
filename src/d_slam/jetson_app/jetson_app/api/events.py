"""Thread-safe local event fan-out for the Jetson Tablet WebSocket."""

from __future__ import annotations

import asyncio
import copy
import threading
import uuid
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Mapping

from ..domain import utc_now


@dataclass(frozen=True)
class _Subscriber:
    loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue[dict[str, Any]]


class EventHub:
    def __init__(
        self,
        *,
        replay_limit: int = 256,
        subscriber_queue_size: int = 128,
        instance_id: str | None = None,
    ) -> None:
        if replay_limit < 1 or subscriber_queue_size < 1:
            raise ValueError("event buffer sizes must be positive")
        self._lock = threading.RLock()
        self._instance_id = instance_id or uuid.uuid4().hex
        self._sequence = 0
        self._events: deque[dict[str, Any]] = deque(maxlen=replay_limit)
        self._subscribers: set[_Subscriber] = set()
        self._subscriber_queue_size = subscriber_queue_size

    @property
    def instance_id(self) -> str:
        return self._instance_id

    def publish(
        self, event_type: str, payload: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        if not isinstance(event_type, str) or not event_type.strip():
            raise ValueError("event_type is required")
        with self._lock:
            self._sequence += 1
            event = {
                "instance_id": self._instance_id,
                "sequence": self._sequence,
                "event_type": event_type,
                "timestamp": utc_now(),
                "payload": copy.deepcopy(dict(payload or {})),
            }
            self._events.append(event)
            subscribers = tuple(self._subscribers)
        for subscriber in subscribers:
            try:
                subscriber.loop.call_soon_threadsafe(
                    self._deliver, subscriber.queue, copy.deepcopy(event)
                )
            except RuntimeError:
                self._discard(subscriber)
        return copy.deepcopy(event)

    @staticmethod
    def _deliver(
        queue: asyncio.Queue[dict[str, Any]], event: dict[str, Any]
    ) -> None:
        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        queue.put_nowait(event)

    def _discard(self, subscriber: _Subscriber) -> None:
        with self._lock:
            self._subscribers.discard(subscriber)

    def _effective_cursor(self, after_sequence: int, instance_id: str | None) -> int:
        if instance_id is not None and instance_id != self._instance_id:
            return 0
        return after_sequence

    async def stream(
        self, *, after_sequence: int = 0, instance_id: str | None = None
    ) -> AsyncIterator[dict[str, Any]]:
        if after_sequence < 0:
            raise ValueError("after_sequence must be non-negative")
        after_sequence = self._effective_cursor(after_sequence, instance_id)
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(
            maxsize=self._subscriber_queue_size
        )
        subscriber = _Subscriber(asyncio.get_running_loop(), queue)
        with self._lock:
            backlog = [
                copy.deepcopy(event)
                for event in self._events
                if event["sequence"] > after_sequence
            ]
            self._subscribers.add(subscriber)
        try:
            for event in backlog[-self._subscriber_queue_size :]:
                yield event
            while True:
                yield await queue.get()
        finally:
            self._discard(subscriber)


__all__ = ["EventHub"]
