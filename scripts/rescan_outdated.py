"""Rescan every leaderboard site that was scanned with older scoring rules, so the ranking compares like with like.

    python scripts/rescan_outdated.py [--base http://localhost:8000] [--parallel 2] [--all]

Uses the running API (force=true). A scan that stops to ask for the site type is confirmed with the type already known for
that site. --all rescans every site, not only the outdated ones.
"""
from __future__ import annotations

import argparse
import asyncio
from typing import Any

import httpx


async def rescan(client: httpx.AsyncClient, sem: asyncio.Semaphore, entry: dict[str, Any]) -> tuple[str, float | None, float | None, str]:
    async with sem:
        domain, before = entry["domain"], entry["ax_score"]
        created = await client.post("/api/scans", json={"url": domain, "force": True})
        if created.status_code != 202:
            return domain, before, None, f"create failed {created.status_code}"
        sid, confirmed = created.json()["scan_id"], False
        for _ in range(150):
            await asyncio.sleep(5)
            try:
                scan = (await client.get(f"/api/scans/{sid}")).json()
            except httpx.HTTPError:
                continue
            if scan["status"] == "needs_confirmation" and not confirmed and entry.get("type"):
                confirmed = True
                await client.post(f"/api/scans/{sid}/confirm", json={"type": entry["type"]})
                continue
            if scan["status"] in ("completed", "failed"):
                score = (scan["score"] or {}).get("ax_score")
                return domain, before, score, scan["status"] if score is None else ""
        return domain, before, None, "timeout"


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--parallel", type=int, default=2)
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()
    async with httpx.AsyncClient(base_url=args.base, timeout=30) as client:
        board = (await client.get("/api/leaderboard")).json()
        todo = [e for e in board["entries"] if args.all or e["outdated"]]
        print(f"scoring version {board['current_version']}: {len(todo)} of {len(board['entries'])} sites to rescan", flush=True)
        sem = asyncio.Semaphore(args.parallel)
        for coro in asyncio.as_completed([rescan(client, sem, e) for e in todo]):
            domain, before, after, note = await coro
            delta = "" if after is None or before is None else f"({after - before:+.1f})"
            print(f"  {domain:22} {before} -> {after} {delta} {note}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
