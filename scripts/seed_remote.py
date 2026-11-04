"""Fill a fresh deployment with scans so the leaderboard and history are not empty.

    python scripts/seed_remote.py --base https://your-app.up.railway.app
    python scripts/seed_remote.py --base http://localhost:8000 --only autotorino.it,flexicar.es

Each domain is scanned through the public API (3 at a time, with its type as a hint), exactly as a visitor would: Muse calls, read-only, robots.txt respected,
and every scan counts against MAX_SCANS_PER_DAY. Sites that block the scanner end as failed scans and are listed at the end.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import time
import urllib.error
import urllib.request

# (domain, type): the type is sent as the scan's type hint, like a visitor picking it on the confirmation screen
DOMAINS = [
    ("autotorino.it", "dealer"), ("flexicar.es", "dealer"), ("clicars.com", "dealer"), ("hahn-gruppe.de", "dealer"),
    ("jeanlain.com", "dealer"), ("lithia.com", "dealer"), ("sonicautomotive.com", "dealer"), ("arnoldclark.com", "dealer"),
    ("outletcars.es", "dealer"),
    ("toyota.ro", "importer"), ("dacia.ro", "importer"), ("renault.ro", "importer"), ("toyota.es", "importer"),
    ("anvelope.pia.ro", "ecommerce"),
]


def call(base: str, path: str, data: dict | None = None) -> dict:
    req = urllib.request.Request(base + path, data=None if data is None else json.dumps(data).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=40) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        try:
            return {"http_error": e.code, **json.loads(e.read().decode())}
        except ValueError:
            return {"http_error": e.code}


def one(base: str, item: tuple[str, str | None], wait_s: float) -> tuple[str, str]:
    domain, hint = item
    body = {"url": domain, **({"type_hint": hint} if hint else {})}
    started = call(base, "/api/scans", body)
    for _ in range(3):  # the server allows 10 new scans a minute: wait and try again
        if (started.get("error") or {}).get("code") != "RATE_LIMITED":
            break
        time.sleep(35)
        started = call(base, "/api/scans", body)
    if "scan_id" not in started:
        return domain, f"not started: {started.get('error', started)}"
    sid, t0 = started["scan_id"], time.time()
    while time.time() - t0 < wait_s:
        scan = call(base, f"/api/scans/{sid}")
        if scan.get("status") in ("completed", "failed", "needs_confirmation"):
            score = scan.get("score") or {}
            err = (scan.get("error") or {}).get("code")
            return domain, f"#{sid} {scan['status']} {scan['site'].get('type')} {score.get('ax_score')} {err or ''}".strip()
        time.sleep(5)
    return domain, f"#{sid} still running after {wait_s:.0f}s"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", required=True)
    ap.add_argument("--only", default="", help="comma-separated domains instead of the default list")
    ap.add_argument("--wait", type=float, default=480, help="seconds to wait for each scan")
    args = ap.parse_args()
    base = args.base.rstrip("/")
    health = call(base, "/health")
    if not health.get("ok"):
        raise SystemExit(f"{base}/health did not answer ok: {health}")
    if not health.get("llm_configured"):
        raise SystemExit("the server has no META_API_KEY: scans would be refused")
    known = dict(DOMAINS)
    items = [(d.strip(), known.get(d.strip())) for d in args.only.split(",") if d.strip()] or DOMAINS

    def staggered(indexed):
        index, item = indexed
        time.sleep(7 * (index % 3))  # three workers: do not start them all in the same second
        return one(base, item, args.wait)

    with cf.ThreadPoolExecutor(3) as pool:
        for domain, result in pool.map(staggered, enumerate(items)):
            print(f"{domain:<22} {result}", flush=True)


if __name__ == "__main__":
    main()
