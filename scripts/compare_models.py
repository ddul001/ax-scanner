"""Benchmark Meta models on the labelled snapshots: accuracy, latency, tokens.

  python scripts/compare_models.py muse-spark-1.3 muse-spark-1.2 [--n 14]
"""
from __future__ import annotations

import asyncio
import csv
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.domain.classification import combine, heuristic  # noqa: E402
from app.services.meta_llm import LlmError, MetaLlm  # noqa: E402
from app.services.signals import extract_signals  # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "data"
HARD = [
    "autohero.com", "clicars.com", "ayvens.com", "totalrenting.es", "vwfs.es", "autodoc.ro", "autotracer.ro",
    "rominserv.ro", "autovit.ro", "coches.net", "volkswagen.ro", "dacia.ro", "autodelrulate.ro", "publi24.ro",
    "bcr.ro", "autoklass.ro",
]


async def one(model: str, row: dict[str, str], sem: asyncio.Semaphore) -> dict[str, Any]:
    snap = json.loads((DATA / "snapshots" / f"{row['domain']}.json").read_text(encoding="utf-8"))
    signals = extract_signals(snap["html"], snap["final_url"], snap["sitemap_urls"])
    heur = heuristic(signals)
    name, _, effort = model.partition("@")
    llm = MetaLlm(model=name, timeout=120, reasoning_effort=effort)
    async with sem:
        started = time.monotonic()
        try:
            out = await llm.classify(signals, heur)
            cls = combine(signals, heur, out)
            return {"domain": row["domain"], "ok": cls.type == row["expected_type"], "type": cls.type,
                    "conf": cls.confidence, "s": time.monotonic() - started, "err": None}
        except LlmError as e:
            return {"domain": row["domain"], "ok": False, "type": "", "conf": 0,
                    "s": time.monotonic() - started, "err": str(e)[:80]}
        finally:
            await llm.aclose()


async def main() -> None:
    models = [a for a in sys.argv[1:] if not a.startswith("--")]
    rows = [r for r in csv.DictReader((DATA / "domains.csv").open(encoding="utf-8"))
            if r["domain"] in HARD and (DATA / "snapshots" / f"{r['domain']}.json").exists()]
    for model in models:
        sem = asyncio.Semaphore(4)
        results = await asyncio.gather(*(one(model, row, sem) for row in rows))
        errs = [r for r in results if r["err"]]
        times = [r["s"] for r in results if not r["err"]]
        print(f"\n{model}: accuracy {sum(r['ok'] for r in results)}/{len(results)} | errors {len(errs)} | "
              f"latency median {statistics.median(times) if times else 0:.1f}s max {max(times) if times else 0:.1f}s")
        for r in results:
            if not r["ok"]:
                print(f"   x {r['domain']:20} got={r['type'] or '-':11} conf={r['conf']} {r['err'] or ''}")


asyncio.run(main())
