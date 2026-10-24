"""Append-only Onshape call ledger with a hard reserve floor (S1).

Every HTTP request to cad.onshape.com must pass through `charge()` BEFORE being
sent, including redirect follow-ups. That ordering is deliberate: if the process
dies mid-request the call is still counted, so the estimate errs toward caution.

No document ids, element ids or keys are ever written to the ledger. Paths are
stored as templates ("/partstudios/d/{did}/w/{wid}/e/{eid}/stl") so the file is
safe to commit or paste into Slack.
"""
import json
import os
import threading
from datetime import datetime, timezone
from typing import Dict, List, Optional

from shared.contracts import OnshapeBudget

DEFAULT_ROOT = os.path.join(".darwin", "ledger")

# Returned as remaining_estimate when no usage-page baseline has been recorded.
UNKNOWN_REMAINING = -1


class BudgetExceeded(RuntimeError):
    """Raised instead of spending a call that would breach the reserve floor."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Ledger(object):
    """One ledger per Onshape account label.

    The reserve is a floor, not a budget: calls are refused once the estimate
    would drop below it, unless `allow_reserve` is set (judging table only).
    """

    def __init__(self, account_label: str, calls_remaining: Optional[int] = None,
                 remaining_at: Optional[str] = None, reserve: int = 0,
                 allow_reserve: bool = False, root: str = DEFAULT_ROOT):
        if not account_label:
            raise ValueError("account_label is required (prod | dev-<name> | mock)")
        self.account_label = account_label
        self.calls_remaining = calls_remaining
        self.remaining_at = remaining_at or None
        self.reserve = int(reserve)
        self.allow_reserve = bool(allow_reserve)
        self.root = root
        self.path = os.path.join(root, "%s.jsonl" % account_label)
        self._lock = threading.Lock()
        self._session_calls = 0
        os.makedirs(root, exist_ok=True)

    @classmethod
    def from_env(cls, root: str = DEFAULT_ROOT) -> "Ledger":
        """Build from the names in .env.example / ~/.darwin_secrets.sh."""
        raw_remaining = (os.environ.get("ONSHAPE_CALLS_REMAINING") or "").strip()
        return cls(
            account_label=(os.environ.get("ONSHAPE_ACCOUNT_LABEL") or "").strip() or "mock",
            calls_remaining=int(raw_remaining) if raw_remaining else None,
            remaining_at=(os.environ.get("ONSHAPE_CALLS_REMAINING_AT") or "").strip() or None,
            reserve=int((os.environ.get("DARWIN_ONSHAPE_RESERVE") or "0").strip() or 0),
            allow_reserve=(os.environ.get("DARWIN_ALLOW_RESERVE") or "0").strip() == "1",
            root=root,
        )

    # ---- reading -------------------------------------------------------

    def _read_lines(self) -> List[Dict]:
        if not os.path.exists(self.path):
            return []
        out = []
        with open(self.path, "r") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue      # a torn final line must not break accounting
        return out

    def _counted(self, entries: List[Dict]) -> int:
        """Calls counted against the baseline: every 'call' line at/after it."""
        calls = [e for e in entries if e.get("kind") == "call"]
        if self.remaining_at:
            return len([e for e in calls if str(e.get("ts", "")) >= self.remaining_at])
        return len(calls)

    def calls_total(self) -> int:
        return self._counted(self._read_lines())

    def remaining_estimate(self) -> int:
        if self.calls_remaining is None:
            return UNKNOWN_REMAINING
        return self.calls_remaining - self.calls_total()

    def hard_stop(self) -> bool:
        if self.allow_reserve:
            return False
        rem = self.remaining_estimate()
        if rem == UNKNOWN_REMAINING:
            # No baseline: safe on a dev account with no floor, refuse otherwise.
            return self.reserve > 0
        return rem <= self.reserve

    def budget_status(self) -> OnshapeBudget:
        total = self.calls_total()
        rem = (UNKNOWN_REMAINING if self.calls_remaining is None
               else self.calls_remaining - total)
        return OnshapeBudget(
            account_label=self.account_label,
            calls_session=self._session_calls,
            calls_ledger_total=total,
            remaining_estimate=rem,
            reserve=self.reserve,
            reserve_unlocked=self.allow_reserve,
            hard_stop=self.hard_stop(),
            last_synced_at=self.remaining_at,
        )

    # ---- writing -------------------------------------------------------

    def charge(self, purpose: str, method: str = "GET", path: str = "") -> int:
        """Count one request before it is sent. Returns the entry's seq.

        Raises BudgetExceeded if spending this call would put the estimate at or
        below the reserve floor.
        """
        with self._lock:
            entries = self._read_lines()
            counted = self._counted(entries)
            seq = 1 + max([int(e.get("seq", 0)) for e in entries] or [0])

            if not self.allow_reserve:
                if self.calls_remaining is None:
                    if self.reserve > 0:
                        raise BudgetExceeded(
                            "no usage-page baseline on '%s': set ONSHAPE_CALLS_REMAINING "
                            "and ONSHAPE_CALLS_REMAINING_AT before spending calls"
                            % self.account_label)
                else:
                    after = self.calls_remaining - counted - 1
                    if after < self.reserve:
                        raise BudgetExceeded(
                            "onshape_budget_reserve: '%s' would drop to %d, floor is %d "
                            "(set DARWIN_ALLOW_RESERVE=1 only at the judging table)"
                            % (self.account_label, after, self.reserve))

            self._append({"kind": "call", "seq": seq, "ts": _now_iso(),
                          "account": self.account_label, "purpose": purpose,
                          "method": method, "path": path, "status": None})
            self._session_calls += 1
            return seq

    def set_status(self, seq: int, status: int) -> None:
        """Record the HTTP status for a charged call. Appends; never counts."""
        with self._lock:
            self._append({"kind": "status", "seq": int(seq),
                          "ts": _now_iso(), "status": int(status)})

    def sync(self, calls_remaining: int, at: Optional[str] = None) -> None:
        """Re-baseline from the Onshape usage page (do this at every checkpoint)."""
        with self._lock:
            self.calls_remaining = int(calls_remaining)
            self.remaining_at = at or _now_iso()
            self._append({"kind": "sync", "seq": 0, "ts": self.remaining_at,
                          "account": self.account_label,
                          "calls_remaining": int(calls_remaining)})

    def _append(self, record: Dict) -> None:
        with open(self.path, "a") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
