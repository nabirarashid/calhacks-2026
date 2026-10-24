import threading

import pytest

from sim import aero


def test_concurrent_first_import_never_falls_back(monkeypatch):
    pytest.importorskip("aerosandbox")
    monkeypatch.setattr(aero, "_ASB", None)
    monkeypatch.setattr(aero, "_ASB_IMPORT_ATTEMPTED", False)
    start = threading.Barrier(8)
    seen = []

    def worker():
        start.wait()
        seen.append(aero._load_aerosandbox())

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(seen) == 8
    assert all(m is not None for m in seen)
