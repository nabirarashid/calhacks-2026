"""Per-run event channels: seq/ts assignment, recording to .darwin/runs/<run_id>.jsonl, and
thread-safe fan-out to websocket subscribers (asyncio queues on the server loop)."""
import asyncio
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel

from shared.events import make_event


def runs_dir() -> Path:
    d = Path(os.environ.get("DARWIN_CACHE_DIR", ".darwin")) / "runs"
    d.mkdir(parents=True, exist_ok=True)
    return d


Subscriber = Tuple[asyncio.AbstractEventLoop, asyncio.Queue]


class Channel:
    def __init__(self, bus: "Bus", run_id: str, record: bool = True) -> None:
        self.bus = bus
        self.run_id = run_id
        self.events = []  # type: List[Dict[str, Any]]
        self.seq = 0
        self.lock = threading.Lock()
        self.subscribers = []  # type: List[Subscriber]
        self.path = runs_dir() / ("%s.jsonl" % run_id) if record else None
        self.done = False

    def emit(self, type_: str, payload: BaseModel) -> Dict[str, Any]:
        with self.lock:
            self.seq += 1
            ev = make_event(type_, self.run_id, self.seq, round(time.time(), 3), payload).model_dump(mode="json")
            self._append(ev)
        return ev

    def emit_raw(self, ev: Dict[str, Any]) -> Dict[str, Any]:
        """Re-emit a recorded event (replay): new run_id/seq/ts, same type and payload."""
        with self.lock:
            self.seq += 1
            out = dict(ev, run_id=self.run_id, seq=self.seq, ts=round(time.time(), 3))
            self._append(out)
        return out

    def _append(self, ev: Dict[str, Any]) -> None:
        self.events.append(ev)
        if ev["type"] == "run_complete":
            self.done = True
        if self.path is not None:
            with self.path.open("a") as f:
                f.write(json.dumps(ev, separators=(",", ":")) + "\n")
        for loop, q in list(self.subscribers) + list(self.bus.wildcard):
            try:
                loop.call_soon_threadsafe(q.put_nowait, ev)
            except RuntimeError:   # loop closed (client gone)
                pass

    def subscribe(self, loop: asyncio.AbstractEventLoop) -> Tuple[List[Dict[str, Any]], asyncio.Queue]:
        q = asyncio.Queue()  # type: asyncio.Queue
        with self.lock:              # backlog + registration atomically: no gaps, no duplicates
            backlog = list(self.events)
            self.subscribers.append((loop, q))
        return backlog, q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self.lock:
            self.subscribers = [s for s in self.subscribers if s[1] is not q]


class Bus:
    def __init__(self) -> None:
        self.channels = {}  # type: Dict[str, Channel]
        self.wildcard = []  # type: List[Subscriber]
        self.lock = threading.Lock()

    def open(self, run_id: str, record: bool = True) -> Channel:
        with self.lock:
            ch = Channel(self, run_id, record=record)
            self.channels[run_id] = ch
            return ch

    def get(self, run_id: str) -> Optional[Channel]:
        return self.channels.get(run_id)

    def subscribe_all(self, loop: asyncio.AbstractEventLoop) -> Tuple[List[Dict[str, Any]], asyncio.Queue]:
        q = asyncio.Queue()  # type: asyncio.Queue
        with self.lock:
            backlog = [e for ch in self.channels.values() for e in list(ch.events)]
            self.wildcard.append((loop, q))
        return backlog, q

    def unsubscribe_all(self, q: asyncio.Queue) -> None:
        with self.lock:
            self.wildcard = [s for s in self.wildcard if s[1] is not q]
