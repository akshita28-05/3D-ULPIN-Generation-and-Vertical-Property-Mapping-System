"""
Resilient Overpass client -- the single place every Overpass call in the app goes through.

Why this exists
---------------
Overpass is a free, shared, volunteer-run service. Any one instance is slow, rate-limited or
unreachable some of the time (and from some networks all of the time). The old code raced all
instances at once with no memory, no retry and no cache, so "Auto-map this view" worked or
failed depending on the exact second you pressed it.

What it does
------------
1. HEALTH-RANKED FAILOVER  Each endpoint has a circuit breaker + latency score. Healthy, fast
   endpoints are tried first; a failing one is parked ("cooldown", growing exponentially, or
   exactly Retry-After on HTTP 429) so we stop wasting seconds on it. It is retried
   automatically once its cooldown ends, so a recovered server rejoins on its own.
2. HEDGED REQUESTS         Best endpoint first; if it hasn't answered after HEDGE_DELAY_S (or has
   failed) the next one is started alongside it -- at most MAX_IN_FLIGHT at once. First success
   wins. Fast when things are fine, polite to the free servers when they aren't.
3. RETRY WITH BACKOFF      If a whole pass fails for transient reasons (timeout, 429, 5xx,
   connection error) we wait (exponential + jitter) and do another pass, within a hard deadline.
4. TILE CACHE              Successful responses are stored on disk keyed by the query. A repeat
   (re-pressing the button, panning back, a demo with no internet) is served instantly, and if
   every endpoint is down a stale entry of ANY age is served instead of an error.
5. SHORT, HONEST ERRORS    A human message for the UI; full technical detail goes to the log.

Configuration (all optional, env vars)
--------------------------------------
OVERPASS_ENDPOINTS        comma-separated list; put your own/self-hosted mirror FIRST
OVERPASS_CACHE_DIR        default ./overpass_cache
OVERPASS_CACHE_TTL_DAYS   fresh window, default 14 (stale entries are still used if live fails)
OVERPASS_OFFLINE=true     never go online; serve only cached tiles
OVERPASS_USER_AGENT       identify your deployment (public instances require a descriptive UA)
"""
import hashlib
import json
import logging
import os
import random
import threading
import time
import concurrent.futures as cf
from datetime import datetime

import requests

logger = logging.getLogger("landsphere.ingestion.overpass")

_DEFAULT_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.openstreetmap.ru/api/interpreter",
]


def _env_endpoints():
    raw = os.getenv("OVERPASS_ENDPOINTS", "").strip()
    eps = [e.strip() for e in raw.split(",") if e.strip()]
    return eps or list(_DEFAULT_ENDPOINTS)


OVERPASS_ENDPOINTS = _env_endpoints()
USER_AGENT = os.getenv("OVERPASS_USER_AGENT", "Vasudha3D-VPMS/1.0 (3D cadastre prototype; contact: admin@vasudha3d.example)")
REQUEST_HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/json"}

CONNECT_TIMEOUT_S = 6          # a dead/blocked host should be abandoned in seconds, not 30
READ_TIMEOUT_S = 30            # a healthy-but-busy server gets this long to run the query
HEDGE_DELAY_S = 4.0            # start the next endpoint if the current one is this slow
MAX_IN_FLIGHT = 2              # never hit more than this many public servers at once
MAX_PASSES = 3                 # full sweeps over the endpoint list before giving up
TOTAL_DEADLINE_S = 75          # hard cap for one query across all passes
BACKOFF_BASE_S = 1.5
CACHE_DIR = os.getenv("OVERPASS_CACHE_DIR", "./overpass_cache")
CACHE_TTL_DAYS = float(os.getenv("OVERPASS_CACHE_TTL_DAYS", "14"))

# Short, user-facing text (details are logged). Kept free of URLs and jargon.
FRIENDLY_FAIL = (
    "The free OpenStreetMap map servers aren't responding right now (they are shared and sometimes busy). "
    "Nothing was lost - press the button again in a minute; areas already downloaded are saved and won't be fetched twice."
)
FRIENDLY_OFFLINE = "Offline mode is on and this area hasn't been downloaded yet."


def offline() -> bool:
    return os.getenv("OVERPASS_OFFLINE", "false").lower() in ("1", "true", "yes")


# ---------------------------------------------------------------------------
# endpoint health (circuit breaker + latency score)
# ---------------------------------------------------------------------------
class _Health:
    __slots__ = ("fails", "cooldown_until", "latency", "last_error", "ok_count", "fail_count")

    def __init__(self):
        self.fails = 0
        self.cooldown_until = 0.0
        self.latency = 5.0          # optimistic-but-neutral prior (seconds) for unknown endpoints
        self.last_error = None
        self.ok_count = 0
        self.fail_count = 0


_lock = threading.Lock()
_health: dict[str, _Health] = {}


def _h(ep: str) -> _Health:
    if ep not in _health:
        _health[ep] = _Health()
    return _health[ep]


def _record_success(ep: str, seconds: float):
    with _lock:
        h = _h(ep)
        h.fails = 0
        h.cooldown_until = 0.0
        h.last_error = None
        h.ok_count += 1
        h.latency = 0.7 * h.latency + 0.3 * max(0.05, seconds)   # EWMA


def _record_failure(ep: str, error: str, retry_after: float | None = None, hard: bool = False):
    """hard=True for statuses that are the *request's* fault (400) -- they say nothing about the endpoint."""
    if hard:
        return
    with _lock:
        h = _h(ep)
        h.fails += 1
        h.fail_count += 1
        h.last_error = error
        if retry_after is not None:
            cool = min(max(retry_after, 5.0), 300.0)
        elif h.fails >= 2:
            cool = min(30.0 * (2 ** (h.fails - 2)), 600.0)    # 30s, 60s, 120s ... max 10 min
        else:
            cool = 0.0                                         # one blip isn't an outage
        h.cooldown_until = time.time() + cool


def ranked_endpoints() -> list[str]:
    """Healthy endpoints fastest-first, then cooling-down ones soonest-to-recover (always at least
    one candidate, so a total outage still gets a half-open probe rather than instantly giving up)."""
    now = time.time()
    with _lock:
        ready, cooling = [], []
        for i, ep in enumerate(OVERPASS_ENDPOINTS):
            h = _h(ep)
            if h.cooldown_until <= now:
                # keep list order as a tiebreak so a user-configured private mirror stays first
                ready.append((h.latency + 0.001 * i, ep))
            else:
                cooling.append((h.cooldown_until, ep))
    return [e for _, e in sorted(ready)] + [e for _, e in sorted(cooling)]


def status() -> list[dict]:
    """For an admin status endpoint / debugging."""
    now = time.time()
    with _lock:
        return [{
            "endpoint": ep,
            "state": "cooling_down" if _h(ep).cooldown_until > now else "ready",
            "retry_in_s": max(0, round(_h(ep).cooldown_until - now)),
            "avg_latency_s": round(_h(ep).latency, 2),
            "ok": _h(ep).ok_count, "failed": _h(ep).fail_count,
            "last_error": _h(ep).last_error,
        } for ep in OVERPASS_ENDPOINTS]


def reset_health():
    with _lock:
        _health.clear()


# ---------------------------------------------------------------------------
# one HTTP attempt
# ---------------------------------------------------------------------------
def query_one_endpoint(endpoint: str, query: str, read_timeout: float | None = None):
    """Single Overpass call. Returns (json, None) or (None, short_error). Never raises.
    Updates the endpoint's health record. (Kept public for older callers.)"""
    t0 = time.time()
    try:
        resp = requests.post(endpoint, data={"data": query}, headers=REQUEST_HEADERS,
                             timeout=(CONNECT_TIMEOUT_S, read_timeout or READ_TIMEOUT_S))
        if resp.status_code != 200:
            ra = None
            if resp.status_code in (429, 503):
                try:
                    ra = float(resp.headers.get("Retry-After", ""))
                except ValueError:
                    ra = 30.0 if resp.status_code == 429 else None
            err = f"{endpoint} HTTP {resp.status_code}"
            _record_failure(endpoint, err, retry_after=ra, hard=(resp.status_code == 400))
            return None, err
        try:
            data = resp.json()
        except ValueError:
            err = f"{endpoint} returned non-JSON (usually an overload page)"
            _record_failure(endpoint, err)
            return None, err
        # Overpass can answer 200 with a "remark" and no elements when it ran out of time/memory.
        remark = data.get("remark", "") if isinstance(data, dict) else ""
        if remark and not data.get("elements") and ("timed out" in remark or "out of memory" in remark or "runtime error" in remark):
            err = f"{endpoint} query aborted by server: {remark[:80]}"
            _record_failure(endpoint, err)
            return None, err
        _record_success(endpoint, time.time() - t0)
        return data, None
    except requests.exceptions.ConnectTimeout:
        err = f"{endpoint} connect timeout"
    except requests.exceptions.ReadTimeout:
        err = f"{endpoint} read timeout"
    except requests.exceptions.ConnectionError as e:
        err = f"{endpoint} unreachable ({type(e).__name__})"
    except Exception as e:  # noqa: BLE001 - this function promises never to raise
        logger.exception("Overpass call crashed via %s", endpoint)
        err = f"{endpoint} failed: {e}"
    _record_failure(endpoint, err)
    return None, err


# ---------------------------------------------------------------------------
# hedged pass over the ranked endpoints
# ---------------------------------------------------------------------------
def _one_pass(query: str, deadline: float):
    order = ranked_endpoints()
    errors: list[str] = []
    ex = cf.ThreadPoolExecutor(max_workers=MAX_IN_FLIGHT, thread_name_prefix="overpass")
    pending: dict[cf.Future, str] = {}
    idx = 0
    try:
        while True:
            # launch the next endpoint if we have capacity and candidates left
            while idx < len(order) and len(pending) < MAX_IN_FLIGHT and time.time() < deadline:
                ep = order[idx]; idx += 1
                remaining = max(3.0, deadline - time.time())
                pending[ex.submit(query_one_endpoint, ep, query, min(READ_TIMEOUT_S, remaining))] = ep
            if not pending:
                return None, errors
            wait_for = HEDGE_DELAY_S if idx < len(order) else max(0.5, deadline - time.time())
            done, _ = cf.wait(list(pending), timeout=wait_for, return_when=cf.FIRST_COMPLETED)
            if not done:
                # current attempt is slow -> hedge: loop will start the next endpoint alongside it
                if idx >= len(order) or time.time() >= deadline:
                    return None, errors + ["timed out waiting for a response"]
                continue
            for f in done:
                pending.pop(f, None)
                data, err = f.result()
                if data is not None:
                    return data, None
                errors.append(err)
    finally:
        ex.shutdown(wait=False, cancel_futures=True)


# ---------------------------------------------------------------------------
# disk cache
# ---------------------------------------------------------------------------
def _cache_path(query: str) -> str:
    key = hashlib.sha1(" ".join(query.split()).encode()).hexdigest()
    return os.path.join(CACHE_DIR, key[:2], f"{key}.json")


def cache_read(query: str, allow_stale: bool):
    """-> (data, age_days) or (None, None)."""
    path = _cache_path(query)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            blob = json.load(fh)
        age = (datetime.utcnow() - datetime.fromisoformat(blob["fetched_at"])).total_seconds() / 86400.0
        if age <= CACHE_TTL_DAYS or allow_stale:
            return blob["data"], age
    except (OSError, ValueError, KeyError):
        pass
    return None, None


def cache_write(query: str, data: dict):
    path = _cache_path(query)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"fetched_at": datetime.utcnow().isoformat(), "data": data}, fh)
        os.replace(tmp, path)            # atomic: a crash can never leave a half-written cache file
    except OSError:
        logger.warning("Could not write Overpass cache entry %s", path)


# ---------------------------------------------------------------------------
# public entry point
# ---------------------------------------------------------------------------
def run_query(query: str, use_cache: bool = True):
    """Fresh cache -> live (hedged, ranked, retried) -> stale cache.
    Returns (data, info) on success where info = {"source": "cache"|"live"|"stale-cache", "age_days": float|None},
    or (None, friendly_error_message) on failure."""
    if use_cache:
        data, age = cache_read(query, allow_stale=False)
        if data is not None:
            return data, {"source": "cache", "age_days": age}

    if offline():
        data, age = cache_read(query, allow_stale=True) if use_cache else (None, None)
        if data is not None:
            return data, {"source": "stale-cache", "age_days": age}
        return None, FRIENDLY_OFFLINE

    deadline = time.time() + TOTAL_DEADLINE_S
    all_errors: list[str] = []
    for attempt in range(MAX_PASSES):
        data, errors = _one_pass(query, deadline)
        if data is not None:
            if use_cache:
                cache_write(query, data)
            return data, {"source": "live", "age_days": 0.0}
        all_errors.extend(errors or [])
        if attempt == MAX_PASSES - 1 or time.time() >= deadline - 2:
            break
        pause = min(BACKOFF_BASE_S * (2 ** attempt) * (0.7 + 0.6 * random.random()), max(0.0, deadline - time.time() - 1))
        logger.info("Overpass pass %d failed (%s); retrying in %.1fs", attempt + 1, "; ".join(errors[-3:]), pause)
        time.sleep(pause)

    logger.warning("All Overpass endpoints failed after %d passes: %s", MAX_PASSES, "; ".join(all_errors[-8:]))
    if use_cache:
        data, age = cache_read(query, allow_stale=True)
        if data is not None:
            logger.warning("Serving stale cached Overpass data (%.1f days old)", age)
            return data, {"source": "stale-cache", "age_days": age}
    return None, FRIENDLY_FAIL