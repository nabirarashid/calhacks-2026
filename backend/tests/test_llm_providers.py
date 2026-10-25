"""Provider selection and the DeepSeek branch of call_model, with HTTP faked (no network, no spend)."""
import json

import pytest

from backend import llm

LLM_ENV = ("DARWIN_LLM_PROVIDER", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY", "DARWIN_MODEL_FAST", "DARWIN_MODEL_DEEP",
           "DEEPSEEK_BASE_URL", "DARWIN_LLM_CACHE", "DARWIN_FAST_THINKING")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    for k in LLM_ENV:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("DARWIN_CACHE_DIR", str(tmp_path))


class Resp:
    def __init__(self, status, data):
        self.status_code, self._data = status, data

    def json(self):
        return self._data


def ok(content, finish="stop"):
    return Resp(200, {"choices": [{"finish_reason": finish, "message": {"content": content, "reasoning_content": "hm"}}],
                      "usage": {"prompt_tokens": 1000, "completion_tokens": 200}})


@pytest.fixture
def deepseek(monkeypatch):
    import httpx
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    sent, replies = [], []
    monkeypatch.setattr(httpx, "post", lambda url, json=None, timeout=None, headers=None:
                        sent.append({"url": url, "body": json, "headers": headers}) or replies.pop(0))
    return sent, replies


def test_provider_defaults(monkeypatch):
    assert llm.provider_name() == "mock"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    assert (llm.provider_name(), llm.fast_model(), llm.deep_model()) == \
        ("anthropic", "claude-haiku-5-5", "claude-sonnet-5-5")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "y")                    # DeepSeek wins when both keys are set
    assert (llm.provider_name(), llm.fast_model(), llm.deep_model()) == \
        ("deepseek", "deepseek-flash", "deepseek-v4-pro")
    monkeypatch.setenv("DARWIN_LLM_PROVIDER", "anthropic")         # explicit choice wins
    assert llm.provider_name() == "anthropic"


def test_other_providers_model_override_is_ignored(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "y")
    monkeypatch.setenv("DARWIN_MODEL_FAST", "claude-haiku-5-5")   # stale line in someone's secrets file
    monkeypatch.setenv("DARWIN_MODEL_DEEP", "deepseek-flash")     # a same-provider override is honored
    assert (llm.fast_model(), llm.deep_model()) == ("deepseek-flash", "deepseek-flash")
    monkeypatch.setenv("DARWIN_LLM_PROVIDER", "replay")
    assert llm.deep_model_or_default() is None


def test_deepseek_json_call(deepseek):
    sent, replies = deepseek
    replies.append(ok('{"a": 1}'))
    r = llm.call_model("plan", "You plan.", "go", {"type": "object"}, model=llm.deep_model(), effort="medium")
    assert r.data == {"a": 1} and r.provider == "deepseek" and r.model == "deepseek-v4-pro"
    body = sent[0]["body"]
    assert sent[0]["url"] == "https://api.deepseek.com/chat/completions"
    assert sent[0]["headers"]["Authorization"] == "Bearer test-key"
    assert body["response_format"] == {"type": "json_object"} and "json" in body["messages"][0]["content"]
    assert body["reasoning_effort"] == "low" and "temperature" not in body
    assert r.cost_usd == pytest.approx(1000 * 1.32e-6 + 200 * 3.96e-6)
    assert llm.SpendLedger.path().name == "spend_deepseek.json"
    assert llm.SpendLedger.read()["calls"] == 1


def test_deepseek_fast_call_disables_thinking_and_retries_bad_json(deepseek):
    sent, replies = deepseek
    replies.extend([ok("not json"), ok('{"b": 2}')])
    r = llm.call_model("parse", "s", "u", {"type": "object"}, think=False)
    assert r.data == {"b": 2} and len(sent) == 2
    assert sent[0]["body"]["reasoning_effort"] == "none" and sent[0]["body"]["model"] == "deepseek-flash"
    assert "previous answer was rejected" in sent[1]["body"]["messages"][1]["content"]


@pytest.mark.parametrize("reply,needle", [
    (ok('{"a": 1}', finish="length"), "max_tokens"),
    (ok("", finish="content_filter"), "refusal"),
    (Resp(402, {"error": {"message": "Insufficient Balance"}}), "HTTP 402 Insufficient Balance"),
])
def test_deepseek_failures_raise_unavailable(deepseek, reply, needle):
    sent, replies = deepseek
    replies.extend([reply] * 3)
    with pytest.raises(llm.LLMUnavailable, match=needle):
        llm.call_model("plan", "s", "u", {"type": "object"})


def test_deepseek_retries_once_on_overload(deepseek, monkeypatch):
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    sent, replies = deepseek
    replies.extend([Resp(503, {}), ok('{"c": 3}')])
    assert llm.call_model("plan", "s", "u", {"type": "object"}).data == {"c": 3}


def test_missing_key_is_unavailable(monkeypatch):
    monkeypatch.setenv("DARWIN_LLM_PROVIDER", "deepseek")
    with pytest.raises(llm.LLMUnavailable, match="DEEPSEEK_API_KEY"):
        llm.call_model("plan", "s", "u", {"type": "object"})


def test_prompt_never_contains_the_key(deepseek):
    sent, replies = deepseek
    replies.append(ok('{"a": 1}'))
    llm.call_model("plan", "s", "u", {"type": "object"})
    assert "test-key" not in json.dumps(sent[0]["body"])
