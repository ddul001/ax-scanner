"""Baseline classification over data/domains.csv with reproducible snapshots.

  python scripts/run_baseline.py --fetch      # fetch homepage+sitemap, save data/snapshots/<domain>.json, classify
  python scripts/run_baseline.py              # replay: classify from saved snapshots only (no network)
  python scripts/run_baseline.py --fetch --only autovit.ro,dacia.ro
  python scripts/run_baseline.py --llm        # also ask Muse Spark per snapshot (needs META_API_KEY in .env)

LLM answers are cached in data/llm/<domain>.json (use --refresh-llm to redo), so reruns are free and reproducible.
Results -> data/baseline_results.csv. Labels in domains.csv are a first guess:
rows with label_confidence=guess need a human check before they are treated as ground truth.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.domain.classification import combine, heuristic  # noqa: E402
from app.domain.models import LlmClassification  # noqa: E402
from app.services.crawler import SafeFetcher, acquire_homepage, load_sitemap_urls  # noqa: E402
from app.services.meta_llm import LlmError, MetaLlm  # noqa: E402
from app.services.signals import extract_signals  # noqa: E402
from app.services.url_normalizer import ScanError, normalize_input  # noqa: E402

DATA = ROOT / "data"
SNAP = DATA / "snapshots"
LLM_DIR = DATA / "llm"
TYPES = ["dealer", "importer", "ecommerce", "marketplace", "finance", "unsupported"]


async def fetch_snapshot(row: dict[str, str], sem: asyncio.Semaphore) -> dict[str, Any]:
    domain = row["domain"]
    async with sem:
        fetcher = SafeFetcher()
        snap: dict[str, Any] = {"domain": domain, "fetched_at": datetime.now(timezone.utc).isoformat(), "error": None}
        try:
            acquired = await acquire_homepage(fetcher, normalize_input(domain))
            sitemap = await load_sitemap_urls(fetcher, acquired)
            snap.update(
                origin=acquired.origin, final_url=acquired.homepage.final_url, status=acquired.homepage.status,
                html=acquired.homepage.text, sitemap_urls=sitemap, fetch_log=fetcher.log,
            )
        except ScanError as e:
            snap["error"] = f"{e.code}: {e.message}"
        finally:
            await fetcher.aclose()
    SNAP.mkdir(parents=True, exist_ok=True)
    (SNAP / f"{domain}.json").write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
    return snap


async def classify(snap: dict[str, Any], llm: MetaLlm | None, refresh: bool) -> dict[str, Any]:
    signals = extract_signals(snap["html"], snap["final_url"], snap.get("sitemap_urls", []))
    heur = heuristic(signals)
    det = combine(signals, heur, None)
    result: dict[str, Any] = {
        "heur_type": det.type, "heur_conf": det.confidence, "predicted": det.type, "confidence": det.confidence,
        "needs_confirmation": det.needs_confirmation, "secondary": "|".join(det.secondary_types),
        "scores": json.dumps(heur.scores), "lang": det.language or "",
        "sitemap_urls": len(snap.get("sitemap_urls", [])),
    }
    if llm is None:
        return result
    cache = LLM_DIR / f"{snap['domain']}.json"
    out = None
    if cache.exists() and not refresh:
        out = LlmClassification.model_validate_json(cache.read_text(encoding="utf-8"))
    else:
        try:
            out = await llm.classify(signals, heur)
            LLM_DIR.mkdir(parents=True, exist_ok=True)
            cache.write_text(out.model_dump_json(indent=1), encoding="utf-8")
        except LlmError as e:
            result["llm_error"] = str(e)
    if out is not None:
        combined = combine(signals, heur, out)
        result.update(llm_type=out.type, llm_conf=out.confidence, llm_secondary="|".join(out.secondary_types),
                      llm_brands="|".join(out.brands), predicted=combined.type, confidence=combined.confidence,
                      needs_confirmation=combined.needs_confirmation, secondary="|".join(combined.secondary_types))
    return result


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--only", default="")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--llm", action="store_true")
    parser.add_argument("--refresh-llm", action="store_true")
    args = parser.parse_args()

    rows = list(csv.DictReader((DATA / "domains.csv").open(encoding="utf-8")))
    if args.only:
        wanted = set(args.only.split(","))
        rows = [r for r in rows if r["domain"] in wanted]

    snaps: dict[str, dict] = {}
    if args.fetch:
        sem = asyncio.Semaphore(args.concurrency)
        for row, snap in zip(rows, await asyncio.gather(*(fetch_snapshot(r, sem) for r in rows))):
            snaps[row["domain"]] = snap
    else:
        for row in rows:
            path = SNAP / f"{row['domain']}.json"
            if path.exists():
                snaps[row["domain"]] = json.loads(path.read_text(encoding="utf-8"))

    llm = MetaLlm() if args.llm else None
    if llm is not None and not llm.configured:
        sys.exit("META_API_KEY is not set. Put it in .env (see .env.example) and rerun with --llm.")
    results = []
    for row in rows:
        snap = snaps.get(row["domain"])
        base = {k: row[k] for k in ("domain", "expected_type", "category", "subtype", "country", "label_confidence")}
        if snap is None:
            results.append({**base, "predicted": "", "error": "NO_SNAPSHOT"})
        elif snap.get("error"):
            results.append({**base, "predicted": "", "error": snap["error"]})
        else:
            results.append({**base, **await classify(snap, llm, args.refresh_llm), "error": ""})

    if llm is not None:
        await llm.aclose()
    fields = ["domain", "expected_type", "category", "subtype", "country", "label_confidence", "heur_type", "heur_conf",
              "llm_type", "llm_conf", "llm_brands", "llm_error", "predicted", "confidence",
              "needs_confirmation", "correct", "secondary", "scores", "lang", "sitemap_urls", "error"]
    for row in results:
        row["correct"] = "" if not row.get("predicted") else str(row["predicted"] == row["expected_type"])
    target = "baseline_results_subset.csv" if args.only else "baseline_results.csv"
    with (DATA / target).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)
    summarize(results)


def summarize(rows: list[dict]) -> None:
    done = [o for o in rows if o.get("predicted")]
    failed = [o for o in rows if not o.get("predicted")]
    auto = [o for o in rows if o.get("predicted") and o["needs_confirmation"] is False]
    print(f"domains={len(rows)} classified={len(done)} errors={len(failed)} auto-accepted(conf>=0.7)={len(auto)}")
    for label, key in (("heuristic", "heur_type"), ("LLM only", "llm_type")):
        have = [o for o in done if o.get(key)]
        if have and (key == "heur_type" or any(o.get("llm_type") for o in done)):
            print(f"accuracy {label}: {sum(o[key] == o['expected_type'] for o in have) / len(have):.0%} ({len(have)})")
    if done:
        acc_all = sum(o["correct"] == "True" for o in done) / len(done)
        print(f"accuracy (final, all classified): {acc_all:.0%}")
    if auto:
        acc = sum(o["correct"] == "True" for o in auto) / len(auto)
        print(f"accuracy (final, auto-accepted only): {acc:.0%}")
    conf: dict[str, Counter] = defaultdict(Counter)
    for o in done:
        conf[o["expected_type"]][o["predicted"]] += 1
    print("\nconfusion (rows=expected, cols=predicted):")
    print(f"{'':12}" + "".join(f"{t[:10]:>11}" for t in TYPES))
    for expected in TYPES:
        print(f"{expected:12}" + "".join(f"{conf[expected][p]:>11}" for p in TYPES))
    print("\nmismatches:")
    for o in done:
        if o["correct"] != "True":
            flag = "?" if o["needs_confirmation"] else " "
            print(f" {flag} {o['domain']:24} expected={o['expected_type']:12} got={o['predicted']:12} "
                  f"conf={o['confidence']} [{o['label_confidence']}] {o['scores']}")
    if failed:
        print("\nerrors:")
        for o in failed:
            print(f"   {o['domain']:24} {o.get('error')}")


if __name__ == "__main__":
    asyncio.run(main())
