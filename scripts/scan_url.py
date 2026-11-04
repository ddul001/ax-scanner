"""Full scan of one domain: classification (Muse if META_API_KEY is set) + dealer checks.

  python scripts/scan_url.py porscheinterauto.ro [--no-llm] [--json out.json]
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session  # noqa: E402

from app.jobs.scan_pipeline import Deps, run_scan  # noqa: E402
from app.repo.db import init_db, make_engine  # noqa: E402
from app.repo.models import Scan, Site  # noqa: E402
from app.services.meta_llm import MetaLlm  # noqa: E402
from app.services.url_normalizer import normalize_input  # noqa: E402

ICON = {"pass": "PASS", "warn": "WARN", "fail": "FAIL", "na": " na ", "skipped": "skip"}


async def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    domain = args[0]
    out_json = sys.argv[sys.argv.index("--json") + 1] if "--json" in sys.argv else None
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    target = normalize_input(domain)
    with Session(engine) as session:
        site = Site(domain=target.host, canonical_origin=target.origin)
        session.add(site)
        session.commit()
        scan = Scan(site_id=site.id)
        session.add(scan)
        session.commit()
        scan_id = scan.id
    llm_on = "--no-llm" not in sys.argv
    await run_scan(scan_id, engine, Deps(llm_factory=(lambda: MetaLlm()) if llm_on else (lambda: None)))
    with Session(engine) as session:
        scan = session.get(Scan, scan_id)
        cls = scan.classification or {}
        print(f"{domain}: status={scan.status} type={cls.get('type')} conf={cls.get('confidence')} method={cls.get('method')}")
        if scan.error_code:
            print("  error:", scan.error_code, scan.error_message)
        rep = scan.report
        if rep:
            print(f"  AX/readiness={rep['readiness']} grade={rep['grade']} (before gate {rep['grade_before_gate']}, gate={rep['gate_checks']})")
            print("  layers:", {layer["layer"]: layer["score"] for layer in rep["layers"]})
            for result in rep["results"]:
                print(f"   [{ICON[result['status']]}] {result['severity']:8} {result['check_id']:22} {result['summary'][:110]}")
            print("  requests:", len(scan.fetch_log or []))
            if out_json:
                Path(out_json).write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")


asyncio.run(main())
