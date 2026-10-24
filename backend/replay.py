"""Replay a recorded run (zero network): re-emit its events with the original gaps x 1/speed.

Recordings are looked up in demo/recordings/, .darwin/runs/, then shared/fixtures/.
The new run gets run_id "replay_..." and design ids are rewritten to match.
"""
import json
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.bus import Bus, Channel, runs_dir

ROOT = Path(__file__).resolve().parent.parent
SEARCH = [ROOT / "demo" / "recordings", None, ROOT / "shared" / "fixtures"]   # None = runs_dir()


def find_recording(name: str) -> Optional[Path]:
    if "/" in name or "\\" in name or not name.endswith(".jsonl"):
        return None
    for d in SEARCH:
        p = (d or runs_dir()) / name
        if p.exists():
            return p
    return None


def list_recordings() -> List[Path]:
    out = []  # type: List[Path]
    for d in SEARCH:
        out += sorted((d or runs_dir()).glob("*.jsonl"))
    return out


def load(path: Path) -> List[Dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def last_summary(events: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    for ev in reversed(events):
        if ev.get("type") in ("run_complete", "run_started"):
            return ev["payload"]["summary"]
    return None


class Replayer:
    def __init__(self, bus: Bus, path: Path, run_id: str, speed: float = 1.0) -> None:
        self.events = load(path)
        self.old_id = self.events[0]["run_id"]
        self.ch = bus.open(run_id, record=False)
        self.speed = max(0.05, float(speed))
        self.stop_flag = threading.Event()
        self.thread = threading.Thread(target=self._run, name="replay-%s" % run_id, daemon=True)

    def start(self) -> Channel:
        self.thread.start()
        return self.ch

    def stop(self) -> None:
        self.stop_flag.set()

    def _run(self) -> None:
        t0_rec = self.events[0]["ts"]
        t0 = time.time()
        for ev in self.events:
            if self.stop_flag.is_set():
                return
            delay = (ev["ts"] - t0_rec) / self.speed - (time.time() - t0)
            if delay > 0:
                time.sleep(min(delay, 30.0))
            remapped = json.loads(json.dumps(ev).replace(self.old_id, self.ch.run_id))
            self.ch.emit_raw(remapped)
