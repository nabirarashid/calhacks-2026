"""call_model: THE one swappable LLM function (PLAN.md S3, B.7).

Providers (env DARWIN_LLM_PROVIDER): anthropic | mock | replay. A new provider
(sponsor credits etc.) is one more branch in _complete() and nothing else.

Guarantees: caps are checked before every attempt (per run + event total);
max_tokens >= 1500; never sends temperature/top_p/top_k (400 since 2026-10-21);
reads the first `text` block (Haiku 5.5 thinks first); checks stop_reason; JSON
via structured output -> json.loads -> regex fallback -> validate -> up to 2
retries with the validation error appended.
"""
import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

from shared.contracts import ModelResult

# USD per million tokens (input, output), checked against the official table 2026-10-23.
PRICES = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "mock": (0.0, 0.0),
}
MIN_MAX_TOKENS = 1500
MAX_ATTEMPTS = 3


class BudgetExceeded(Exception):
    """A per-run or event-wide LLM cap would be exceeded. Callers fall back to rules."""


class LLMUnavailable(Exception):
    """The provider failed, refused, timed out, or never produced valid output."""


def provider_name() -> str:
    default = "anthropic" if os.environ.get("ANTHROPIC_API_KEY") else "mock"
    return os.environ.get("DARWIN_LLM_PROVIDER", default)


def fast_model() -> str:
    return os.environ.get("DARWIN_MODEL_FAST", "claude-haiku-5-5")


def deep_model() -> str:
    return os.environ.get("DARWIN_MODEL_DEEP", "claude-sonnet-5-5")


def _state_dir() -> Path:
    d = Path(os.environ.get("DARWIN_CACHE_DIR", ".darwin"))
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------- budgets

class RunLLMBudget:
    """Per-run caps; one instance per run, shared by all its agent threads."""

    def __init__(self, max_calls: int, max_spend_usd: float) -> None:
        self.max_calls = max_calls
        self.max_spend_usd = max_spend_usd
        self.calls = 0
        self.spend_usd = 0.0
        self._lock = threading.Lock()

    def check(self) -> None:
        with self._lock:
            if self.calls >= self.max_calls:
                raise BudgetExceeded("run call cap %d reached" % self.max_calls)
            if self.spend_usd >= self.max_spend_usd:
                raise BudgetExceeded("run spend cap $%.2f reached" % self.max_spend_usd)

    def charge(self, cost: float) -> None:
        with self._lock:
            self.calls += 1
            self.spend_usd += cost


class SpendLedger:
    """Event-wide local spend ledger (.darwin/spend.json). The Anthropic Console is ground truth."""

    _lock = threading.Lock()

    @staticmethod
    def path() -> Path:
        return _state_dir() / "spend.json"

    @classmethod
    def read(cls) -> Dict[str, float]:
        try:
            return json.loads(cls.path().read_text())
        except (OSError, ValueError):
            return {"total_usd": 0.0, "calls": 0}

    @classmethod
    def cap(cls) -> float:
        return float(os.environ.get("DARWIN_SPEND_CAP_TOTAL_USD", "4.50"))

    @classmethod
    def check(cls) -> None:
        if cls.read()["total_usd"] >= cls.cap():
            raise BudgetExceeded("event spend cap $%.2f reached" % cls.cap())

    @classmethod
    def charge(cls, cost: float) -> None:
        if cost <= 0:
            return
        with cls._lock:
            s = cls.read()
            s["total_usd"] = round(s["total_usd"] + cost, 6)
            s["calls"] = int(s.get("calls", 0)) + 1
            cls.path().write_text(json.dumps(s))


def cost_usd(model: str, tokens_in: int, tokens_out: int) -> float:
    p_in, p_out = PRICES.get(model, PRICES["claude-sonnet-5-5"])   # unknown model: price conservatively
    return tokens_in * p_in / 1e6 + tokens_out * p_out / 1e6


# ---------------------------------------------------------------- JSON extraction

def extract_json(text: str) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except ValueError:
        pass
    m = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, dict) else None
    except ValueError:
        return None


# ---------------------------------------------------------------- cache

def _cache_key(model: str, system: str, user: str, schema: Optional[dict]) -> str:
    blob = json.dumps([model, system, user, schema], sort_keys=True)  # thinking mode does not change the answer contract
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def _cache_path(key: str) -> Path:
    d = _state_dir() / "llm_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d / ("%s.json" % key)


# ---------------------------------------------------------------- providers

_client = None
_client_lock = threading.Lock()


def _anthropic_client(timeout_s: float):
    global _client
    with _client_lock:
        if _client is None:
            import anthropic
            _client = anthropic.Anthropic(max_retries=1, timeout=timeout_s)
    return _client


def _complete(provider: str, role: str, system: str, user: str, schema: Optional[dict], model: str,
              max_tokens: int, effort: str, timeout_s: float, think: bool = True) -> Tuple[str, int, int]:
    """One raw completion. Returns (text, tokens_in, tokens_out). Raises LLMUnavailable."""
    if provider == "mock":
        from shared.mocks import fake_llm
        r = fake_llm.call_model(role, system, user, schema, model=model, max_tokens=max_tokens, effort=effort)
        return r.raw_text, r.tokens_in, r.tokens_out
    if provider == "anthropic":
        import anthropic
        output_config = {"effort": effort}  # type: Dict[str, Any]
        if schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": schema}
        extra = {}  # type: Dict[str, Any]
        # Haiku 5.5 accepts thinking "disabled" at effort <= high; other current models 400 on it.
        if not think and model.startswith("claude-haiku-5") and effort in ("low", "medium", "high"):
            extra["thinking"] = {"type": "disabled"}
        try:
            resp = _anthropic_client(timeout_s).with_options(timeout=timeout_s).messages.create(
                model=model, max_tokens=max(max_tokens, MIN_MAX_TOKENS), system=system,
                messages=[{"role": "user", "content": user}], output_config=output_config, **extra)
        except anthropic.APIStatusError as e:
            raise LLMUnavailable("%s: HTTP %s" % (type(e).__name__, e.status_code))
        except anthropic.APIConnectionError as e:   # includes APITimeoutError
            raise LLMUnavailable(type(e).__name__)
        tokens_in, tokens_out = resp.usage.input_tokens, resp.usage.output_tokens
        if resp.stop_reason == "refusal":
            raise LLMUnavailable("refusal")
        if resp.stop_reason == "max_tokens":
            raise LLMUnavailable("max_tokens")
        text = next((b.text for b in resp.content if getattr(b, "type", None) == "text"), "")
        return text, tokens_in, tokens_out
    raise LLMUnavailable("unknown provider %r" % provider)


# ---------------------------------------------------------------- the one function

def call_model(role: str, system: str, user: str, schema: Optional[dict] = None, *, model: Optional[str] = None,
               max_tokens: int = 2000, effort: str = "low", timeout_s: float = 40.0,
               validate: Optional[Callable[[Dict[str, Any]], Any]] = None,
               budget: Optional[RunLLMBudget] = None, think: bool = True) -> ModelResult:
    """Call the configured provider and return validated JSON in ModelResult.data.

    `validate(data)` may raise to reject the output (it is retried with the error
    appended). `think=False` turns Haiku thinking off (latency; critical-path roles),
    unless DARWIN_FAST_THINKING=1. Raises BudgetExceeded or LLMUnavailable.
    """
    provider = provider_name()
    model = model or (fast_model() if provider != "mock" else "mock")
    think = think or os.environ.get("DARWIN_FAST_THINKING") == "1"
    use_cache = provider == "replay" or os.environ.get("DARWIN_LLM_CACHE") == "1"
    t0 = time.perf_counter()
    total_in = total_out = 0
    total_cost = 0.0
    prompt = user
    last_err = "no attempts"

    for attempt in range(MAX_ATTEMPTS):
        key = _cache_key(model, system, prompt, schema)
        cached = None
        if use_cache and _cache_path(key).exists():
            cached = json.loads(_cache_path(key).read_text())
        if cached is not None:
            text, t_in, t_out, cost = cached["raw_text"], cached["tokens_in"], cached["tokens_out"], 0.0
        else:
            if provider == "replay":
                raise LLMUnavailable("replay cache miss for %s" % role)
            if budget is not None:
                budget.check()
            SpendLedger.check()
            text, t_in, t_out = _complete(provider, role, system, prompt, schema, model, max_tokens, effort, timeout_s,
                                          think)
            cost = cost_usd(model, t_in, t_out)
            if budget is not None:
                budget.charge(cost)
            SpendLedger.charge(cost)
        total_in += t_in
        total_out += t_out
        total_cost += cost

        data = extract_json(text)
        if data is None:
            last_err = "output was not a JSON object"
        else:
            try:
                if validate is not None:
                    validate(data)
                if use_cache and cached is None:
                    _cache_path(key).write_text(json.dumps({"raw_text": text, "tokens_in": t_in, "tokens_out": t_out}))
                return ModelResult(data=data, raw_text=text, model=model, provider=provider, tokens_in=total_in,
                                   tokens_out=total_out, cost_usd=round(total_cost, 6),
                                   latency_ms=(time.perf_counter() - t0) * 1000.0, cached=cached is not None)
            except Exception as e:  # noqa: BLE001 — any validation error triggers a retry
                last_err = str(e).splitlines()[0][:300]
        prompt = (user + "\n\nYour previous answer was rejected: %s\n"
                         "Reply with ONLY one JSON object that matches the schema." % last_err)
    raise LLMUnavailable("invalid output after %d attempts: %s" % (MAX_ATTEMPTS, last_err))
