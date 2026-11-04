"""Run Step 0 against real domains: python scripts/classify_url.py example.ro [more...] [--llm] [--render]

Prints type, confidence and top evidence. Uses the Meta API only with --llm (needs META_API_KEY).
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.classifier import run_step0  # noqa: E402
from app.services.crawler import SafeFetcher  # noqa: E402
from app.services.meta_llm import MetaLlm  # noqa: E402
from app.services.renderer import render_html  # noqa: E402
from app.services.url_normalizer import ScanError, normalize_input  # noqa: E402


async def one(domain: str, use_llm: bool, render: bool) -> None:
    fetcher = SafeFetcher()
    llm = MetaLlm() if use_llm else None
    try:
        result = await run_step0(
            normalize_input(domain), fetcher=fetcher, llm=llm, renderer=render_html if render else None
        )
        cls = result.classification
        print(f"{domain:32} {cls.type:11} conf={cls.confidence:<5} confirm={cls.needs_confirmation!s:5} "
              f"method={cls.method} secondary={cls.secondary_types} scores={cls.heuristic['scores']} "
              f"lang={cls.language} js={cls.js_rendered} origin={result.canonical_origin}")
    except ScanError as e:
        print(f"{domain:32} ERROR {e.code}: {e.message}")
    finally:
        await fetcher.aclose()
        if llm:
            await llm.aclose()


async def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    for domain in args:
        await one(domain, "--llm" in flags, "--render" in flags)


if __name__ == "__main__":
    asyncio.run(main())
