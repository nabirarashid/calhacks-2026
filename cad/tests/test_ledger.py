"""Ledger arithmetic, reserve refusal and thread safety. Zero network."""
import threading

import pytest

from cad.ledger import BudgetExceeded, Ledger, UNKNOWN_REMAINING


def mk(tmp_path, **kw):
    kw.setdefault("account_label", "dev-test")
    kw.setdefault("calls_remaining", 100)
    kw.setdefault("reserve", 10)
    return Ledger(root=str(tmp_path), **kw)


def test_counts_and_estimates(tmp_path):
    led = mk(tmp_path)
    assert led.calls_total() == 0
    assert led.remaining_estimate() == 100
    for _ in range(5):
        led.charge("spike", "GET", "/elements/d/{did}/w/{wid}/e/{eid}/configuration")
    assert led.calls_total() == 5
    assert led.remaining_estimate() == 95
    assert led.budget_status().calls_session == 5


def test_refuses_at_reserve_floor(tmp_path):
    """90 calls available above a floor of 10; the 91st must be refused."""
    led = mk(tmp_path, calls_remaining=100, reserve=10)
    for _ in range(90):
        led.charge("build", "GET", "/stl")
    assert led.remaining_estimate() == 10
    with pytest.raises(BudgetExceeded) as exc:
        led.charge("build", "GET", "/stl")
    assert "onshape_budget_reserve" in str(exc.value)
    assert led.calls_total() == 90, "a refused call must not be counted"


def test_unlock_allows_spending_into_reserve(tmp_path):
    led = mk(tmp_path, calls_remaining=100, reserve=10)
    for _ in range(90):
        led.charge("build", "GET", "/stl")
    led.allow_reserve = True
    led.charge("judging", "GET", "/stl")
    assert led.calls_total() == 91
    assert led.budget_status().reserve_unlocked is True
    assert led.budget_status().hard_stop is False


def test_hard_stop_flag_tracks_floor(tmp_path):
    led = mk(tmp_path, calls_remaining=12, reserve=10)
    assert led.hard_stop() is False
    led.charge("build")
    assert led.hard_stop() is False      # estimate 11, floor 10
    led.charge("build")
    assert led.hard_stop() is True       # estimate 10, at the floor


def test_no_baseline_is_open_on_dev_and_closed_on_prod(tmp_path):
    """A dev account with no floor may spend; a prod floor refuses until synced."""
    dev = mk(tmp_path, account_label="dev-nabira", calls_remaining=None, reserve=0)
    assert dev.remaining_estimate() == UNKNOWN_REMAINING
    assert dev.hard_stop() is False
    dev.charge("spike")

    prod = mk(tmp_path, account_label="prod", calls_remaining=None, reserve=400)
    assert prod.hard_stop() is True
    with pytest.raises(BudgetExceeded) as exc:
        prod.charge("build")
    assert "baseline" in str(exc.value)


def test_sync_rebaselines(tmp_path):
    led = mk(tmp_path, calls_remaining=100, reserve=0)
    for _ in range(10):
        led.charge("build")
    assert led.remaining_estimate() == 90
    led.sync(2400)
    assert led.calls_total() == 0, "calls before the new baseline are excluded"
    assert led.remaining_estimate() == 2400
    assert led.budget_status().last_synced_at is not None


def test_set_status_does_not_count(tmp_path):
    led = mk(tmp_path)
    seq = led.charge("build", "GET", "/stl")
    led.set_status(seq, 200)
    assert led.calls_total() == 1


def test_no_secrets_or_ids_in_ledger(tmp_path):
    led = mk(tmp_path)
    led.charge("build", "GET", "/partstudios/d/{did}/w/{wid}/e/{eid}/stl")
    with open(led.path) as fh:
        text = fh.read()
    assert "{did}" in text
    for bad in ("sk-ant-", "ONSHAPE_SECRET", "ONSHAPE_ACCESS"):
        assert bad not in text


def test_thread_safety_8x50(tmp_path):
    """8 threads x 50 charges must count exactly 400, with no lost updates."""
    led = mk(tmp_path, calls_remaining=10000, reserve=0)
    errors = []

    def worker():
        try:
            for _ in range(50):
                led.charge("build", "GET", "/stl")
        except Exception as exc:          # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert led.calls_total() == 400
    assert led.remaining_estimate() == 10000 - 400


def test_concurrent_charges_never_breach_floor(tmp_path):
    """Under contention the floor must still hold exactly."""
    led = mk(tmp_path, calls_remaining=60, reserve=50)   # exactly 10 spendable
    granted = []
    refused = []

    def worker():
        for _ in range(10):
            try:
                led.charge("build")
                granted.append(1)
            except BudgetExceeded:
                refused.append(1)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(granted) == 10, "exactly the spendable calls, no more"
    assert len(refused) == 30
    assert led.remaining_estimate() == 50
