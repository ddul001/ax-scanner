"""Scoring stability: transient failures are retried, the WAF probe confirms before it blames, scores carry a rules version."""
from __future__ import annotations

import httpx
import pytest

from app.checks.context import build_context
from app.checks.engine import load_template, run_checks
from app.domain.scoring import SCORING_VERSION
from app.services.crawler import SafeFetcher, acquire_homepage
from app.services.url_normalizer import ScanError, normalize_input
from tests.conftest import html_page, public_resolver
from tests.site_builder import HOST, build_site


def fetcher_for(handler):
    return SafeFetcher(transport=httpx.MockTransport(handler), resolver=public_resolver)


@pytest.mark.anyio
async def test_transient_statuses_and_connection_errors_are_retried_once():
    calls = {"n": 0}

    def flaky(request):
        calls["n"] += 1
        return httpx.Response(503, text="busy") if calls["n"] == 1 else html_page("<html>ok</html>")

    f = fetcher_for(flaky)
    r = await f.fetch("https://a.example/", kind="t")
    assert r.status == 200 and calls["n"] == 2
    await f.aclose()

    calls["n"] = 0

    def drops(request):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("reset")
        return html_page("<html>ok</html>")

    f = fetcher_for(drops)
    assert (await f.fetch("https://a.example/", kind="t")).status == 200 and calls["n"] == 2
    await f.aclose()


@pytest.mark.anyio
async def test_a_403_is_an_answer_not_a_transient_failure_and_retries_can_be_switched_off():
    calls = {"n": 0}

    def blocked(request):
        calls["n"] += 1
        return httpx.Response(403, text="no")

    f = fetcher_for(blocked)
    assert (await f.fetch("https://a.example/", kind="t")).status == 403 and calls["n"] == 1
    await f.aclose()

    calls["n"] = 0
    f = fetcher_for(lambda r: (calls.__setitem__("n", calls["n"] + 1), httpx.Response(503, text="x"))[1])
    assert (await f.fetch("https://a.example/", kind="t", retries=0)).status == 503 and calls["n"] == 1
    await f.aclose()

    def down(request):
        raise httpx.ConnectError("down")

    f = fetcher_for(down)
    with pytest.raises(ScanError) as e:
        await f.fetch("https://a.example/", kind="t")
    assert e.value.code == "UNREACHABLE"
    await f.aclose()


async def waf(handler_wrap):
    web, factory = build_site()
    inner = web.handler

    def handler(request):
        return handler_wrap(request, inner)

    fetcher = factory()
    acq = await acquire_homepage(fetcher, normalize_input(HOST))
    ctx = await build_context(acq, HOST, "dealer", fetcher, lambda **kw: SafeFetcher(transport=httpx.MockTransport(handler), resolver=public_resolver, **kw), delay_s=0)
    res = {r.check_id: r for r in await run_checks(ctx, load_template("dealer"))}
    await fetcher.aclose()
    return res["disc.waf_ua"]


@pytest.mark.anyio
async def test_one_blocked_probe_that_recovers_on_retry_is_intermittent_not_a_failure():
    seen = {"gpt": 0}

    def handler(request, inner):
        ua = request.headers.get("user-agent", "")
        if "GPTBot" in ua and request.url.path == "/":
            seen["gpt"] += 1
            if seen["gpt"] == 1:
                return httpx.Response(429, text="slow down")
        return inner(request)

    r = await waf(handler)
    assert r.status == "pass" and "intermittent" in r.summary and r.details["intermittent"] == ["GPTBot"]
    assert r.details["probe"]["GPTBot"]["attempts"] == 2 and r.details["probe"]["GPTBot"]["recovered"] is True


@pytest.mark.anyio
async def test_a_block_that_repeats_is_confirmed_and_fails():
    def handler(request, inner):
        if "ClaudeBot" in request.headers.get("user-agent", "") and request.url.path == "/":
            return httpx.Response(403, text="no bots")
        return inner(request)

    r = await waf(handler)
    assert r.status == "fail" and "confirmed on a second attempt" in r.summary and r.missing == ["ClaudeBot"]


@pytest.mark.anyio
async def test_page_size_noise_between_requests_does_not_warn():
    count = {"n": 0}

    def handler(request, inner):
        resp = inner(request)
        if request.url.path == "/" and request.url.scheme == "https":
            count["n"] += 1
            pad = "x" * (1000 if count["n"] % 2 else 1100)  # a rotating token / ad slot changes the size a little
            return httpx.Response(resp.status_code, headers=resp.headers, text=resp.text.replace("</body>", f"<!--{pad}--></body>"))
        return resp

    assert (await waf(handler)).status == "pass"


def test_reports_carry_the_scoring_version_and_the_leaderboard_flags_older_ones():
    from fastapi.testclient import TestClient
    from sqlmodel import Session
    from app.jobs.scan_pipeline import Deps
    from app.main import create_app
    from app.repo.db import make_engine
    from app.repo.models import Scan, Site
    from app.domain.scoring import build_report

    assert build_report("dealer", {"discovery": 100}, []).scoring_version == SCORING_VERSION
    engine = make_engine("sqlite:///:memory:")
    app = create_app(engine=engine, deps=Deps(run_checks=False))
    with TestClient(app) as c:
        with Session(engine) as s:
            a = Site(domain="a.example", canonical_origin="https://a.example", type="dealer")
            b = Site(domain="b.example", canonical_origin="https://b.example", type="dealer")
            s.add(a); s.add(b); s.commit(); s.refresh(a); s.refresh(b)
            s.add(Scan(site_id=a.id, status="completed", ax_score=60, grade="C", report={"layers": [], "scoring_version": SCORING_VERSION}))
            s.add(Scan(site_id=b.id, status="completed", ax_score=70, grade="C", report={"layers": [], "scoring_version": "2026-10-30.1"}))
            s.commit()
        body = c.get("/api/leaderboard").json()
    assert body["current_version"] == SCORING_VERSION
    assert {e["domain"]: e["outdated"] for e in body["entries"]} == {"a.example": False, "b.example": True}


# ---------------- Muse calls and journeys ----------------
@pytest.mark.anyio
async def test_a_muse_call_that_times_out_or_gets_429_is_retried_once():
    import json as _json

    from app.services.meta_llm import LlmError, MetaLlm
    from pydantic import BaseModel

    class Out(BaseModel):
        ok: bool

    calls = {"n": 0}

    def timeout_then_ok(request):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ReadTimeout("slow")
        return httpx.Response(200, json={"choices": [{"message": {"content": _json.dumps({"ok": True})}}]})

    llm = MetaLlm(api_key="k", base_url="https://api.test/v1", transport=httpx.MockTransport(timeout_then_ok))
    assert (await llm.structured("s", "u", Out)).ok is True and calls["n"] == 2
    await llm.aclose()

    calls["n"] = 0

    def busy_then_ok(request):
        calls["n"] += 1
        return httpx.Response(429, text="busy") if calls["n"] == 1 else httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true}'}}]})

    llm = MetaLlm(api_key="k", base_url="https://api.test/v1", transport=httpx.MockTransport(busy_then_ok))
    assert (await llm.structured("s", "u", Out)).ok is True and calls["n"] == 2
    await llm.aclose()

    llm = MetaLlm(api_key="k", base_url="https://api.test/v1", transport=httpx.MockTransport(lambda r: httpx.Response(401, text="no")))
    with pytest.raises(LlmError):  # an auth error is not transient and is not retried into a different answer
        await llm.structured("s", "u", Out)
    await llm.aclose()


@pytest.mark.anyio
async def test_a_journey_stuck_in_a_loop_gets_a_second_attempt_and_the_best_verdict_counts():
    from app.journey.agent import AgentStep
    from tests.test_journey import good_find, run

    def stuck_then_fine(page, step, data):
        if "previous attempt did not finish" in data["task"]:
            return good_find(page, step, data)
        return AgentStep(thought="again", action="goto", url="https://a.example/stoc/")

    res, llm, _ = await run(stuck_then_fine)
    r = res["ux.j_find"]
    assert r.status == "pass" and r.summary.endswith("(second attempt)")
    assert [a["status"] for a in r.details["attempts"]] == ["fail", "pass"] and r.details["attempts"][0]["stop_reason"] == "loop"


@pytest.mark.anyio
async def test_two_failed_attempts_stay_a_fail_and_a_pass_is_never_repeated():
    from app.journey.agent import AgentStep
    from tests.test_journey import good_find, run

    res, *_ = await run(lambda p, s, u: AgentStep(thought="again", action="goto", url="https://a.example/stoc/"))
    r = res["ux.j_find"]
    assert r.status == "fail" and len(r.details["attempts"]) == 2

    res, llm, _ = await run(good_find)
    assert res["ux.j_find"].status == "pass" and len(res["ux.j_find"].details["attempts"]) == 1  # no second run after a pass
