import json

import httpx
import pytest

from app.domain.classification import combine, heuristic
from app.domain.models import LlmClassification
from app.services.meta_llm import LlmError, MetaLlm
from app.services.signals import extract_signals
from tests.conftest import read_fixture


def signals(name="dealer-lite.html", url="https://a.example/"):
    s = extract_signals(read_fixture(name), url)
    return s, heuristic(s)


def reply(obj, status=200):
    content = obj if isinstance(obj, str) else json.dumps(obj)
    return httpx.Response(status, json={"choices": [{"message": {"content": content}}]})


GOOD = {
    "type": "dealer", "confidence": 0.9, "secondary_types": [], "brands": ["Skoda"], "locations": 1,
    "evidence": [{"signal": "vin_count", "value": "3 VINs"}, {"signal": "made_up_signal", "value": "x"}],
}


def llm_with(handler):
    return MetaLlm(api_key="k", base_url="https://api.test/v1", transport=httpx.MockTransport(handler))


@pytest.mark.anyio
async def test_llm_happy_path_sends_json_schema_and_compressed_payload():
    seen = {}

    def handler(req):
        seen.update(json.loads(req.content), auth=req.headers["authorization"], url=str(req.url))
        return reply(GOOD)

    s, h = signals()
    out = await llm_with(handler).classify(s, h)
    assert out.type == "dealer"
    assert seen["url"] == "https://api.test/v1/chat/completions" and seen["auth"] == "Bearer k"
    assert seen["temperature"] == 0 and seen["response_format"]["type"] == "json_schema"
    user = seen["messages"][1]["content"]
    assert "text_excerpt" in json.loads(user) and "<html" not in user.lower()


@pytest.mark.anyio
async def test_llm_accepts_code_fences():
    s, h = signals()
    out = await llm_with(lambda r: reply("```json\n" + json.dumps(GOOD) + "\n```")).classify(s, h)
    assert out.confidence == 0.9


@pytest.mark.anyio
async def test_llm_retries_once_on_invalid_json():
    calls = []

    def handler(req):
        calls.append(1)
        return reply("not json") if len(calls) == 1 else reply(GOOD)

    s, h = signals()
    assert (await llm_with(handler).classify(s, h)).type == "dealer" and len(calls) == 2


@pytest.mark.anyio
async def test_llm_fails_after_second_invalid():
    s, h = signals()
    with pytest.raises(LlmError):
        await llm_with(lambda r: reply({"type": "banana", "confidence": 3})).classify(s, h)


@pytest.mark.anyio
async def test_llm_falls_back_when_json_schema_unsupported():
    bodies = []

    def handler(req):
        body = json.loads(req.content)
        bodies.append(body)
        return httpx.Response(400, json={"error": "response_format"}) if "response_format" in body else reply(GOOD)

    s, h = signals()
    assert (await llm_with(handler).classify(s, h)).type == "dealer"
    assert "response_format" not in bodies[-1]


@pytest.mark.anyio
@pytest.mark.parametrize("status", [401, 429, 500])
async def test_llm_http_errors(status):
    s, h = signals()
    with pytest.raises(LlmError):
        await llm_with(lambda r: httpx.Response(status)).classify(s, h)


@pytest.mark.anyio
async def test_llm_network_error_and_missing_key():
    def boom(req):
        raise httpx.ConnectTimeout("t")

    s, h = signals()
    with pytest.raises(LlmError):
        await llm_with(boom).classify(s, h)
    with pytest.raises(LlmError):
        await MetaLlm(api_key="").classify(s, h)


def test_agreement_keeps_muse_confidence_plus_small_bonus():
    s, h = signals()
    c = combine(s, h, LlmClassification(type="dealer", confidence=0.8))
    assert c.type == "dealer" and c.method == "deterministic+llm"
    assert c.confidence == round(0.8 + 0.05 * h.confidence, 2)


def test_muse_decides_type_even_against_confident_heuristic_and_confidence_drops():
    s, h = signals()
    c = combine(s, h, LlmClassification(type="importer", confidence=0.7))
    assert c.type == "importer"  # Muse is the arbiter
    assert c.confidence == round(0.7 - 0.25 * h.confidence, 2) and c.needs_confirmation
    assert any("heuristic disagreed" in e.value for e in c.evidence if e.signal == "heuristic")


def test_weak_heuristic_does_not_drag_down_a_confident_muse():
    s, h = signals("ambiguous.html", "https://a.example/")
    c = combine(s, h, LlmClassification(type="dealer", confidence=0.93))
    assert c.type == "dealer" and c.confidence >= 0.7 and not c.needs_confirmation


def test_heuristic_role_reported_by_muse_as_secondary_is_not_a_conflict():
    s = extract_signals(read_fixture("dealer-with-shop.html"), "https://a.example/")
    h = heuristic(s)
    llm = LlmClassification.model_validate(
        {"type": "dealer", "confidence": 0.9, "secondary_types": ["ecommerce"],
         "facts": {"is_automotive_related": True, "owns_vehicle_stock": True, "sells_auto_parts_online": True}})
    h2 = h.model_copy(update={"top": "ecommerce", "confidence": 0.85})
    c = combine(s, h2, llm)
    assert c.type == "dealer" and c.confidence == 0.9 and "ecommerce" in c.secondary_types


def test_secondary_types_come_from_facts_when_muse_omits_them():
    s, h = signals()
    llm = LlmClassification.model_validate(
        {"type": "dealer", "confidence": 0.9,
         "facts": {"is_automotive_related": True, "owns_vehicle_stock": True, "sells_auto_parts_online": True}})
    assert "ecommerce" in combine(s, h, llm).secondary_types


def test_muse_unsupported_vote_is_respected_with_penalty_scaled_by_heuristic_confidence():
    s, h = signals()
    c = combine(s, h, LlmClassification(type="unsupported", confidence=0.9))
    assert c.type == "unsupported"
    assert c.confidence == round(0.9 - 0.25 * h.confidence, 2)


def test_llm_evidence_and_brands_are_validated():
    s, h = signals()
    llm = LlmClassification.model_validate({**GOOD, "brands": ["Skoda", "Ferrari"]})
    c = combine(s, h, llm)
    assert [e.signal for e in c.evidence if e.source == "llm"] == ["vin_count"]
    assert "Skoda" in c.brands and "Ferrari" not in c.brands


def test_user_hint_only_nudges():
    s, h = signals("ambiguous.html", "https://a.example/")
    base = combine(s, h, None)
    hinted = combine(s, h, None, hint=base.type)
    assert hinted.confidence == round(min(1, base.confidence + 0.1), 2)
    other = combine(s, h, None, hint="ecommerce" if base.type != "ecommerce" else "dealer")
    assert other.type == base.type and other.confidence == base.confidence


def test_threshold_is_configurable():
    s, h = signals()
    assert combine(s, h, None, threshold=1.01).needs_confirmation


FACTS_FINANCE = {"is_automotive_related": True, "is_financial_institution": True, "owns_vehicle_stock": True}


def test_facts_override_inconsistent_model_label():
    llm = LlmClassification.model_validate({"type": "dealer", "confidence": 0.9, "facts": FACTS_FINANCE})
    assert llm.type == "finance" and llm.model_type == "dealer"


@pytest.mark.parametrize(
    "facts,expected",
    [
        ({"is_automotive_related": True, "is_manufacturer_or_official_importer": True,
          "hosts_third_party_listings": True, "owns_vehicle_stock": True}, "importer"),
        ({"is_automotive_related": True, "hosts_third_party_listings": True, "owns_vehicle_stock": True}, "marketplace"),
        ({"is_automotive_related": True, "owns_vehicle_stock": True, "sells_auto_parts_online": True}, "dealer"),
        ({"is_automotive_related": True, "sells_auto_parts_online": True}, "ecommerce"),
        ({"is_automotive_related": False}, "unsupported"),
    ],
)
def test_fact_priority(facts, expected):
    assert LlmClassification.model_validate({"type": "dealer", "confidence": 0.9, "facts": facts}).type == expected


def test_inconclusive_facts_keep_model_label():
    llm = LlmClassification.model_validate(
        {"type": "importer", "confidence": 0.8, "facts": {"is_automotive_related": True}})
    assert llm.type == "importer"


def test_payload_carries_rich_context_and_derives_type_from_facts():
    s, h = signals("finance-leasing.html", "https://leasing.example/")
    from app.services.meta_llm import build_payload
    p = build_payload(s, h)
    assert p["headings"] and p["footer_text"] and "cookie" not in p["text_excerpt"].lower()
    assert "headings" not in p["signals"] and "footer_text" not in p["signals"]


def test_parse_model_tolerates_prose_around_json():
    from app.journey.agent import AgentStep
    from app.services.meta_llm import parse_model
    good = '{"thought": "t", "action": "finish", "link_index": null, "url": null, "answer": null}'
    for wrapped in (good, "```json\n" + good + "\n```", "I looked at the page. " + good, good + "\nHope this helps!"):
        assert parse_model(wrapped, AgentStep).action == "finish"
    with pytest.raises(Exception):
        parse_model("no json here", AgentStep)


@pytest.mark.anyio
async def test_structured_reports_reasoning_tokens_when_asked():
    from pydantic import BaseModel

    class Out(BaseModel):
        ok: bool

    def handler(req):
        return httpx.Response(200, json={
            "choices": [{"message": {"content": '{"ok": true}'}}],
            "usage": {"completion_tokens": 40, "completion_tokens_details": {"reasoning_tokens": 31}},
        })

    usage: dict = {}
    out = await llm_with(handler).structured("sys", "user", Out, usage=usage)
    assert out.ok and usage == {"reasoning_tokens": 31, "completion_tokens": 40}
    assert (await llm_with(handler).structured("sys", "user", Out)).ok  # usage stays optional
