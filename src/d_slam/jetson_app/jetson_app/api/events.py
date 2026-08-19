from __future__ import annotations
import asyncio, threading
from datetime import datetime, timezone
from typing import Any, Mapping

class EventSubscription:
    def __init__(self, hub, identifier, queue): self.hub, self.identifier, self.queue = hub, identifier, queue
    async def get(self): return await self.queue.get()
    def close(self): self.hub.unsubscribe(self.identifier)

class EventHub:
    def __init__(self, *, queue_size: int = 256): self.queue_size=queue_size; self._lock=threading.RLock(); self._next=1; self._subs={}
    def subscribe(self):
        queue=asyncio.Queue(maxsize=self.queue_size)
        with self._lock: identifier=self._next; self._next+=1; self._subs[identifier]=queue
        return EventSubscription(self,identifier,queue)
    def unsubscribe(self, identifier):
        with self._lock: self._subs.pop(identifier,None)
    def publish(self, event_type: str, payload: Mapping[str,Any] | None=None):
        event={"event_type":event_type,"created_at":datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),"payload":dict(payload or {})}
        with self._lock: queues=tuple(self._subs.values())
        for queue in queues:
            if queue.full():
                try: queue.get_nowait()
                except asyncio.QueueEmpty: pass
            try: queue.put_nowait(event)
            except asyncio.QueueFull: pass
        return event
