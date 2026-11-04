"""A minimal brand site (demo/sample-brand-site, plain HTML + a little JS) on which ux.j_dealer passes: a positive control for the verifier.

Offline tests use a scripted agent; the live tests (opt-in: RUN_LIVE_LLM=1 and META_API_KEY) use the real Muse agent.
"""
from __future__ import annotations

import os

import pytest

from app.journey.agent import AgentStep
from tests.demo_site_runner import SITE, run
from tests.test_journey import FakeLlm, finish, link


def good_agent(page, step, _):
    if step == 1:
        return AgentStep(thought="dealer network", action="open_link", link_index=link(page, "/dealeri.html"))
    if step == 2:
        return AgentStep(thought="Bucharest dealer", action="open_link", link_index=link(page, "bucuresti-nord"))
    return finish(found=True, url=page["url"], dealer_name="Velora București Nord", address="Șos. București-Ploiești nr. 12, București",
                  phone="021 300 4001", email="nord@velora-dealer.ro")


def test_the_demo_site_is_plain_html_with_the_dealer_data_in_the_markup():
    html = (SITE / "dealeri.html").read_text(encoding="utf-8")
    assert html.count('class="dealer"') == 8 and "021 300 4001" in html and "<script src=\"/assets/site.js\">" in html
    assert "fetch(" not in html  # the list is not loaded by script
    assert "li.hidden" in (SITE / "assets" / "site.js").read_text(encoding="utf-8")  # JS only filters what is already there


@pytest.mark.anyio
async def test_rules_alone_find_everything_the_journey_needs_on_the_demo_site():
    res, report, ctx, requests = await run(None)
    assert res["net.locator"].status == "pass" and res["act.test_drive_route"].status == "pass" and res["id.schema_org"].status == "pass"
    assert res["ux.j_dealer"].status == "skipped"  # no LLM: skipped, not failed
    assert {r.method for r in requests} == {"GET"}


@pytest.mark.anyio
async def test_scripted_agent_passes_ux_j_dealer_on_the_demo_site():
    res, report, ctx, requests = await run(FakeLlm(good_agent), discovery=False)
    r = res["ux.j_dealer"]
    assert r.status == "pass", r.summary
    assert r.details["verification"]["checks"] == {"name_on_page": True, "phone_or_email_on_page": True, "address_on_page": True, "in_requested_city": True}
    assert r.details["journey"]["goal"].startswith("A customer in Bucharest") and any(m in r.details["journey"]["goal"] for m in ("Velora Aria", "Velora Terra", "Velora Lumo"))
    assert report.layers[5].layer == "agent_ux" and report.layers[5].score == 100.0


@pytest.mark.anyio
async def test_the_same_agent_fails_when_the_dealer_list_is_filled_by_javascript_only():
    def lost(page, step, _):
        if step == 1:
            return AgentStep(thought="dealer network", action="open_link", link_index=link(page, "/dealeri.html"))
        return finish(found=False, notes="the dealer list is empty in the HTML")

    res, *_ = await run(FakeLlm(lost), js_only=True, discovery=False)
    assert res["ux.j_dealer"].status == "fail"
    assert res["net.locator"].status == "fail"  # the deterministic locator check agrees: nothing readable without JS


LIVE = pytest.mark.skipif(os.environ.get("RUN_LIVE_LLM") != "1", reason="live Muse run: set RUN_LIVE_LLM=1 (needs META_API_KEY)")


@LIVE
@pytest.mark.anyio
async def test_live_real_agent_passes_on_the_demo_site():
    from app.services.meta_llm import MetaLlm

    llm = MetaLlm()
    try:
        res, report, ctx, requests = await run(llm)
    finally:
        await llm.aclose()
    r = res["ux.j_dealer"]
    assert r.status == "pass", (r.summary, r.details.get("journey", {}).get("steps"))
    assert {x.method for x in requests} == {"GET"}


@LIVE
@pytest.mark.anyio
async def test_live_real_agent_fails_when_the_list_is_javascript_only():
    from app.services.meta_llm import MetaLlm

    llm = MetaLlm()
    try:
        res, *_ = await run(llm, js_only=True)
    finally:
        await llm.aclose()
    assert res["ux.j_dealer"].status in ("fail", "warn")


def test_the_demo_agent_card_and_poppy_document_are_valid_against_the_aap_schemas():
    import json

    jsonschema = pytest.importorskip("jsonschema")
    referencing = pytest.importorskip("referencing")
    from referencing.jsonschema import DRAFT202012

    schemas = SITE.parent.parent / "aap-v3.0-spec" / "schemas"
    if not schemas.is_dir():
        pytest.skip("aap-v3.0-spec is not included in the repository (clone auto-agent-protocol into it to run this test)")
    registry = referencing.Registry()
    for p in schemas.rglob("*.json"):
        doc = json.loads(p.read_text(encoding="utf-8"))
        res = referencing.Resource.from_contents(doc, default_specification=DRAFT202012)
        registry = registry.with_resource(doc.get("$id") or p.name, res).with_resource(p.name, res)

    def errors(doc: str, schema: str):
        v = jsonschema.Draft202012Validator(json.loads((schemas / schema).read_text(encoding="utf-8")), registry=registry)
        return [e.message[:120] for e in v.iter_errors(json.loads((SITE / ".well-known" / doc).read_text(encoding="utf-8")))]

    assert errors("agent-card.json", "agent-card.schema.json") == []
    assert errors("poppy.json", "poppy-document.schema.json") == []
    card = json.loads((SITE / ".well-known" / "agent-card.json").read_text(encoding="utf-8"))
    mcp = card["capabilities"]["extensions"][0]["params"]["mcp"]
    assert mcp["public_read"] is False  # no live endpoint: the card must not claim a readable one


@pytest.mark.anyio
async def test_the_scanner_sees_the_card_and_the_protocol_layer_passes():
    res, report, ctx, requests = await run(None)
    assert res["proto.aap_card"].status == "pass" and not res["proto.aap_card"].not_adopted
    assert res["proto.aap_card"].details["aap_version"] == "3.0"
    assert next(l for l in report.layers if l.layer == "protocol").score == 100.0
