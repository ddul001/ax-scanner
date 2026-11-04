"""Step 0 orchestration: target -> fetch -> signals -> heuristic (+LLM) -> Classification."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.config import settings
from app.domain.classification import combine, heuristic
from app.domain.models import Classification, HeuristicResult, LlmClassification, Signals
from app.services.crawler import SafeFetcher, acquire_homepage, load_sitemap_urls
from app.services.meta_llm import LlmError, MetaLlm
from app.services.renderer import Renderer, render_html
from app.services.signals import extract_signals
from app.services.url_normalizer import Target

log = logging.getLogger(__name__)


@dataclass
class Step0Result:
    classification: Classification
    canonical_origin: str
    fetch_log: list[dict[str, Any]] = field(default_factory=list)


async def run_step0(
    target: Target,
    *,
    fetcher: SafeFetcher,
    llm: MetaLlm | None,
    renderer: Renderer | None = render_html,
    hint: str | None = None,
    ignore_robots: bool = False,
) -> Step0Result:
    acquired = await acquire_homepage(fetcher, target, ignore_robots=ignore_robots)
    sitemap = await load_sitemap_urls(fetcher, acquired)
    html = acquired.homepage.text
    signals = extract_signals(html, acquired.homepage.final_url, sitemap)

    js_rendered = False
    if signals.js_shell and renderer is not None:
        rendered = await renderer(acquired.homepage.final_url)
        if rendered:
            signals = extract_signals(rendered, acquired.homepage.final_url, sitemap)
            js_rendered = True

    heur = heuristic(signals)
    llm_result = await _try_llm(llm, signals, heur)
    classification = combine(
        signals, heur, llm_result,
        hint=hint, threshold=settings.confirm_threshold, js_rendered=js_rendered,
    )
    return Step0Result(classification, acquired.origin, list(fetcher.log))


async def _try_llm(llm: MetaLlm | None, signals: Signals, heur: HeuristicResult) -> LlmClassification | None:
    if llm is None or not llm.configured:
        return None
    try:
        return await llm.classify(signals, heur)
    except LlmError as e:  # degrade to deterministic-only
        log.warning("LLM classification unavailable: %s", e)
        return None
