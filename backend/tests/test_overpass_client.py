"""Resilience tests for the Overpass client -- fully offline (requests.post is faked)."""
import time
from datetime import datetime, timedelta
import json

import pytest
import requests

from app.ingestion import overpass_client as oc, osm_overpass

A, B, C = "https://a.test/api", "https://b.test/api", "https://c.test/api"
GOOD = {"elements": [{"type": "way", "id": 1, "tags": {"building": "yes"},
                      "geometry": [{"lat": 28.6301, "lon": 77.2201}, {"lat": 28.6301, "lon": 77.2205},
                                   {"lat": 28.6305, "lon": 77.2205}, {"lat": 28.6305, "lon": 77.2201}]}]}


class Resp:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code, self._body, self.headers = status, body if body is not None else GOOD, headers or {}

    def json(self):
        if self._body == "NOTJSON":
            raise ValueError("no json")
        return self._body


@pytest.fixture(autouse=True)
def fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(oc, "OVERPASS_ENDPOINTS", [A, B, C])
    monkeypatch.setattr(osm_overpass, "OVERPASS_ENDPOINTS", [A, B, C])
    monkeypatch.setattr(oc, "CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(oc, "BACKOFF_BASE_S", 0.01)
    monkeypatch.setattr(oc, "HEDGE_DELAY_S", 0.2)
    monkeypatch.setattr(osm_overpass, "TILE_REQUEST_DELAY_S", 0)
    monkeypatch.delenv("OVERPASS_OFFLINE", raising=False)
    oc.reset_health()
    yield


def fake(monkeypatch, behaviour):
    calls = []

    def post(url, data=None, headers=None, timeout=None):
        calls.append(url)
        out = behaviour(url, len(calls))
        if isinstance(out, Exception):
            raise out
        return out
    monkeypatch.setattr(oc.requests, "post", post)
    return calls


def test_fails_over_to_next_endpoint(monkeypatch):
    calls = fake(monkeypatch, lambda u, n: requests.exceptions.ConnectionError() if u == A else Resp())
    data, info = oc.run_query("q1")
    assert data == GOOD and info["source"] == "live"
    assert A in calls and (B in calls or C in calls)


def test_dead_endpoint_is_parked_then_ranked_last(monkeypatch):
    # one blip is tolerated; the second consecutive failure opens the circuit breaker
    oc._record_failure(A, "boom")
    assert {e["endpoint"]: e for e in oc.status()}[A]["state"] == "ready"
    oc._record_failure(A, "boom")
    st = {e["endpoint"]: e for e in oc.status()}
    assert st[A]["state"] == "cooling_down" and st[B]["state"] == "ready"
    assert oc.ranked_endpoints()[-1] == A            # last resort only while cooling down
    oc._record_success(A, 0.2)                       # a recovered server rejoins immediately
    assert {e["endpoint"]: e for e in oc.status()}[A]["state"] == "ready"


def test_failing_endpoint_loses_traffic_to_the_one_that_works(monkeypatch):
    calls = fake(monkeypatch, lambda u, n: requests.exceptions.ConnectTimeout() if u == A else Resp())
    for i in range(4):
        assert oc.run_query(f"q{i}", use_cache=False)[0] is not None
    assert calls.count(A) == 1                       # tried once, then never again: B/C answered faster


def test_429_retry_after_is_honoured(monkeypatch):
    fake(monkeypatch, lambda u, n: Resp(429, {}, {"Retry-After": "60"}) if u == A else Resp())
    assert oc.run_query("q", use_cache=False)[0] is not None
    st = {e["endpoint"]: e for e in oc.status()}
    assert st[A]["state"] == "cooling_down" and 50 <= st[A]["retry_in_s"] <= 61


def test_cache_prevents_second_network_call(monkeypatch):
    calls = fake(monkeypatch, lambda u, n: Resp())
    oc.run_query("same")
    n = len(calls)
    data, info = oc.run_query("same")
    assert info["source"] == "cache" and len(calls) == n


def test_stale_cache_served_when_everything_is_down(monkeypatch):
    fake(monkeypatch, lambda u, n: Resp())
    oc.run_query("old")
    path = oc._cache_path("old")
    blob = json.load(open(path))
    blob["fetched_at"] = (datetime.utcnow() - timedelta(days=90)).isoformat()
    json.dump(blob, open(path, "w"))
    monkeypatch.setattr(oc, "MAX_PASSES", 2)
    fake(monkeypatch, lambda u, n: requests.exceptions.ConnectionError())
    data, info = oc.run_query("old")
    assert data == GOOD and info["source"] == "stale-cache" and info["age_days"] > 80


def test_total_outage_returns_short_friendly_message(monkeypatch):
    monkeypatch.setattr(oc, "MAX_PASSES", 2)
    fake(monkeypatch, lambda u, n: requests.exceptions.ConnectionError())
    data, msg = oc.run_query("nothing-cached")
    assert data is None and "http" not in msg and len(msg) < 300


def test_hedging_beats_a_slow_first_endpoint(monkeypatch):
    def beh(u, n):
        if u == A:
            time.sleep(1.5)
        return Resp()
    fake(monkeypatch, beh)
    oc._record_success(A, 0.1); oc._record_success(B, 3.0); oc._record_success(C, 4.0)   # A ranked first
    t0 = time.time()
    data, _ = oc.run_query("slow", use_cache=False)
    assert data is not None and time.time() - t0 < 1.2


def test_non_json_overload_page_counts_as_failure(monkeypatch):
    fake(monkeypatch, lambda u, n: Resp(200, "NOTJSON") if u == A else Resp())
    assert oc.run_query("q", use_cache=False)[0] == GOOD


def test_offline_mode_uses_only_cache(monkeypatch):
    calls = fake(monkeypatch, lambda u, n: Resp())
    oc.run_query("warm")
    monkeypatch.setenv("OVERPASS_OFFLINE", "true")
    n = len(calls)
    assert oc.run_query("warm")[0] == GOOD and len(calls) == n
    data, msg = oc.run_query("cold")
    assert data is None and "Offline" in msg and len(calls) == n


# ---- grid tiling + end-to-end buildings fetch --------------------------------------------------
def test_grid_cells_are_stable_across_overlapping_views():
    t1 = set(osm_overpass._grid_tiles(28.6301, 77.2201, 28.6402, 77.2302))
    t2 = set(osm_overpass._grid_tiles(28.6350, 77.2250, 28.6450, 77.2350))
    assert t1 & t2                                          # shared cells ...
    for cell in t1 & t2:                                    # ... with byte-identical query text
        assert osm_overpass._overpass_query_for_bbox(*cell) == osm_overpass._overpass_query_for_bbox(*cell)
    assert all(abs((n - s) - osm_overpass.GRID_DEG) < 1e-9 for s, w, n, e in t1)


def test_fetch_buildings_end_to_end_and_retry_only_fetches_missing_cells(monkeypatch):
    bbox = (28.6300, 77.2200, 28.6420, 77.2220)             # spans 2 cells vertically
    cells = osm_overpass._grid_tiles(*bbox)
    assert len(cells) == 2
    bad_cell_query = osm_overpass._overpass_query_for_bbox(*cells[1])
    state = {"fail": True}

    def post(url, data=None, headers=None, timeout=None):
        if state["fail"] and data["data"] == bad_cell_query:
            raise requests.exceptions.ConnectionError()
        return Resp()
    monkeypatch.setattr(oc.requests, "post", post)
    monkeypatch.setattr(oc, "MAX_PASSES", 1)

    buildings, warning = osm_overpass.fetch_buildings_in_bbox(*bbox)
    assert len(buildings) == 1 and "1 of 2" in warning          # partial success is reported honestly

    state["fail"] = False
    sent = []
    monkeypatch.setattr(oc.requests, "post", lambda url, data=None, **k: (sent.append(data["data"]), Resp())[1])
    buildings, warning = osm_overpass.fetch_buildings_in_bbox(*bbox)
    assert warning is None and sent == [bad_cell_query]         # good cell came from cache; only the missing one fetched


def test_total_failure_returns_none_and_short_message(monkeypatch):
    monkeypatch.setattr(oc, "MAX_PASSES", 1)
    fake(monkeypatch, lambda u, n: requests.exceptions.ConnectionError())
    buildings, msg = osm_overpass.fetch_buildings_in_bbox(28.63, 77.22, 28.632, 77.222)
    assert buildings is None and "OpenStreetMap" in msg and "http" not in msg


def test_legacy_race_function_still_returns_data_error_pair(monkeypatch):
    fake(monkeypatch, lambda u, n: Resp())
    data, err = osm_overpass._race_overpass_query("legacy")
    assert data == GOOD and err is None