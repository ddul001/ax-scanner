"""act.webmcp: static detection of WebMCP tools (declarative toolname attributes + registerTool calls in same-site scripts)."""
from __future__ import annotations

import pytest

from app.checks.webmcp import _imperative
from tests.test_checks_shop import FakeShopLlm, build_shop, good_journey
from app.checks.context import build_context
from app.checks.engine import load_template, run_checks
from app.services.crawler import acquire_homepage
from app.services.url_normalizer import normalize_input

HOST = "s.example"
SCRIPT = """
// thin WebMCP adapter
const tools = [
  { name: 'search_winter_wheel_sets', description: 'Search winter wheel sets by vehicle brand and model.', inputSchema: {type: 'object'} },
  { name: 'request_offer', description: 'Ask for an offer; the human confirms and sends it.', inputSchema: {type: 'object', properties: {name: {type: 'string'}}} },
];
navigator.modelContext.provideContext({ tools });
"""


def test_imperative_tools_are_read_from_registration_code():
    got = {t["name"]: t for t in _imperative(SCRIPT, "https://s.example/a.js")}
    assert set(got) == {"search_winter_wheel_sets", "request_offer"}  # property names such as 'name' / 'type' are not tools
    assert "Search winter wheel sets" in got["search_winter_wheel_sets"]["description"]
    assert _imperative("const x = {name: 'some_helper', description: 'not a tool at all, no registration'}", "u") == []


async def scan(patch=None, llm=None):
    web, factory = build_shop(cart=False, quote=True)
    if patch:
        patch(web.routes)
    fetcher = factory()
    acq = await acquire_homepage(fetcher, normalize_input(HOST))
    ctx = await build_context(acq, HOST, "ecommerce", fetcher, factory, delay_s=0, llm=llm)
    ctx.llm = llm
    results = {r.check_id: r for r in await run_checks(ctx, load_template("ecommerce"))}
    await fetcher.aclose()
    return results


def with_webmcp(auto=False):
    def patch(routes):
        form = ("<form toolname='request_offer' tooldescription='Request an offer for a set of tyres. The user confirms.'"
                + (" toolautosubmit" if auto else "") + "><input name='nume' required><button>Trimite</button></form>")
        routes[f"{HOST}/"] = routes[f"{HOST}/"].__class__(200, headers=routes[f"{HOST}/"].headers, text=routes[f"{HOST}/"].text.replace("<h1>", form + "<h1>", 1)
                                                         .replace("</body>", "<script src='/assets/agent/webmcp.js'></script></body>"))
        routes[f"{HOST}/assets/agent/webmcp.js"] = (200, {"content-type": "text/javascript"}, SCRIPT)
    return patch


@pytest.mark.anyio
async def test_declared_tools_are_listed_and_nothing_is_run():
    res = await scan(with_webmcp())
    r = res["act.webmcp"]
    assert r.status == "pass" and r.severity == "INFO"
    assert set(r.found) == {"request_offer", "search_winter_wheel_sets"} and r.details["executed"] is False
    kinds = {t["name"]: t["kind"] for t in r.details["tools"]}
    assert kinds == {"request_offer": "declarative", "search_winter_wheel_sets": "imperative"}
    assert "auto-submit" not in r.summary


@pytest.mark.anyio
async def test_auto_submitting_tools_are_called_out():
    r = (await scan(with_webmcp(auto=True)))["act.webmcp"]
    assert "auto-submit" in r.summary and "request_offer" in r.summary


@pytest.mark.anyio
async def test_no_webmcp_is_na_and_a_quote_only_shop_stays_fail():
    res = await scan()
    assert res["act.webmcp"].status == "na" and res["act.add_to_cart"].status == "fail"


@pytest.mark.anyio
async def test_webmcp_offer_tool_softens_the_missing_add_to_cart():
    res = await scan(with_webmcp(), FakeShopLlm(journey=good_journey))
    r = res["act.add_to_cart"]
    assert r.status == "warn" and "request_offer" in r.summary and r.details["webmcp_tool"] == "request_offer"
    assert "Nothing was run" in r.summary


@pytest.mark.anyio
async def test_webmcp_without_a_manifest_is_a_warn_for_the_protocol_check():
    r = (await scan(with_webmcp()))["proto.mcp_public"]
    assert r.status == "warn" and not r.not_adopted and "WebMCP tools are declared" in r.summary and "no MCP server or UCP manifest" in r.summary
    none = (await scan())["proto.mcp_public"]
    assert none.status == "fail" and none.not_adopted  # nothing declared at all stays a fail
