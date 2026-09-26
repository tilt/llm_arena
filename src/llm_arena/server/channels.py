"""Per-run event fan-out: every event is kept (so a page opened mid-run can replay) and pushed to live subscribers."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from llm_arena.runner.events import RunEvent, RunFinished


class RunChannel:
    def __init__(self) -> None:
        self.history: list[RunEvent] = []
        self._subscribers: list[asyncio.Queue[RunEvent]] = []

    @property
    def finished(self) -> bool:
        return bool(self.history) and isinstance(self.history[-1], RunFinished)

    def publish(self, event: RunEvent) -> None:
        self.history.append(event)
        for queue in self._subscribers:
            queue.put_nowait(event)

    async def subscribe(self) -> AsyncIterator[RunEvent]:
        """Replay the history, then follow live events until the run finishes."""
        queue: asyncio.Queue[RunEvent] = asyncio.Queue()
        replay = list(self.history)
        self._subscribers.append(queue)
        try:
            for event in replay:
                yield event
            if replay and isinstance(replay[-1], RunFinished):
                return
            while True:
                event = await queue.get()
                yield event
                if isinstance(event, RunFinished):
                    return
        finally:
            self._subscribers.remove(queue)


class Channels:
    def __init__(self) -> None:
        self._channels: dict[str, RunChannel] = {}

    def get(self, run_id: str) -> RunChannel:
        return self._channels.setdefault(run_id, RunChannel())

    def __contains__(self, run_id: object) -> bool:
        return run_id in self._channels
