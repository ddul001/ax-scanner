"""The discovery summary behind the report's Discovery tab: how each kind of page was found."""
from __future__ import annotations

import pytest

from app.services import link_resolver
from app.services.discovery_view import attach_usage
from tests.demo_site_runner import run as run_demo
from tests.test_dealer_llm import FakeDealerLlm, WrongTestDriveLlm, build_de_dealer, scan


@pytest.fixture(autouse=True)
def _clear_cache():
    link_resolver._CACHE.clear()  # picks are cached per link list; each test brings its own model answers


def rows(ctx):
    return {r["role"]: r for r in ctx.discovery["roles"]}


@pytest.mark.anyio
async def test_llm_picks_are_described_with_their_reason_and_the_rules_alternative():
    res, report, ctx = await scan(build_de_dealer, FakeDealerLlm())
    d, r = ctx.discovery, rows(ctx)
    assert d["mode"] == "llm_first" and d["sources"]["pages_read"] >= 7
    assert r["stock_list"]["state"] == "found" and r["stock_list"]["source"] == "llm" and r["stock_list"]["read"] is True
    assert r["stock_list"]["reason"] == "fake" and "picked it from the homepage links" in r["stock_list"]["how"]
    assert r["test_drive"]["url"].endswith("/termin-vereinbaren") and r["test_drive"]["http_status"] == 200
    assert r["faq"]["state"] == "not_found" and r["faq"]["url"] is None and r["faq"]["source"] == "none"
    assert d["items"]["source"] == "llm" and len(d["items"]["urls"]) >= 3 and "category list" in d["items"]["how"] or d["items"]["role"] == "vdp"
    s = d["summary"]
    assert s["categories"] == 6 and s["found"] == 5 and s["by_llm"] == 5 and s["not_found"] == 1


@pytest.mark.anyio
async def test_a_rejected_pick_says_why_and_a_missing_category_is_shown_as_missing():
    _, _, ctx = await scan(build_de_dealer, WrongTestDriveLlm())
    td = rows(ctx)["test_drive"]
    assert td["state"] == "rejected" and "does not look like this category" in td["how"] and td["url"].endswith("/ueber-uns")
    assert ctx.discovery["summary"]["rejected"] == 1


@pytest.mark.anyio
async def test_without_an_llm_the_rules_are_credited_and_the_mode_says_so():
    _, _, ctx = await scan(build_de_dealer, None)
    d = ctx.discovery
    assert d["mode"] == "rules_only" and d["summary"]["by_llm"] == 0
    assert all(r["source"] in ("rules", "none") for r in d["roles"])


@pytest.mark.anyio
async def test_pages_are_linked_to_the_checks_that_used_them():
    res, report, ctx, requests = await run_demo(None)
    assert ctx.discovery["mode"] == "rules_only"
    attach_usage(ctx.discovery, list(res.values()))
    locator = rows(ctx)["locator"]
    assert locator["state"] == "found" and "net.locator" in locator["used_by"]
    assert any(m["used_by"] for m in ctx.discovery["items"]["urls"])  # model pages feed the model checks
    attach_usage(None, [])  # nothing to annotate is not an error


def test_an_ignored_duplicate_pick_shows_the_page_that_was_really_used():
    from types import SimpleNamespace

    from app.services.discovery_view import _row

    page = SimpleNamespace(url="https://x.example/new-cars/aygo/build", ok=True, status=200)
    row = _row("configurator", {"url": "https://x.example/new-cars", "source": "rules", "ignored": "same page as another role"}, page)
    assert row["url"] == "https://x.example/new-cars/aygo/build" and row["source"] == "rules" and "same page as another category" in row["how"]


def test_expected_pages_follow_the_site_type():
    from app.services.discovery_view import expected_pages
    dealer = [p["role"] for p in expected_pages("dealer")]
    assert dealer == ["stock_list", "test_drive", "service", "contact", "financing", "faq"]
    assert {"configurator", "locator"} <= {p["role"] for p in expected_pages("importer")}
    assert {"cart", "checkout"} <= {p["role"] for p in expected_pages("ecommerce")}
    assert all(p["label"] for p in expected_pages("importer"))
    assert expected_pages("finance") == [] and expected_pages(None) == []
