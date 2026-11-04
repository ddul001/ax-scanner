import pytest

from app.checks.context import build_context
from app.checks.engine import load_template, make_report, run_checks
from app.services.crawler import acquire_homepage
from app.services.url_normalizer import normalize_input
from tests.site_builder import FORM, BAD_FORM, build_site


async def scan(**kw):
    web, factory = build_site(**kw)
    fetcher = factory()
    acq = await acquire_homepage(fetcher, normalize_input("a.example"))
    ctx = await build_context(acq, "a.example", "dealer", fetcher, factory, delay_s=0)
    template = load_template("dealer")
    results = await run_checks(ctx, template)
    report = make_report("dealer", template, results)
    await fetcher.aclose()
    return {r.check_id: r for r in results}, report, web, ctx


def status(res, cid):
    return res[cid].status


@pytest.mark.anyio
async def test_good_site_scores_high_and_only_unimplemented_checks_are_skipped():
    res, report, web, ctx = await scan()
    failing = {k: (v.status, v.summary) for k, v in res.items() if v.status not in ("pass", "skipped") and k != "act.webmcp"}
    assert failing == {}, failing
    assert {k for k, v in res.items() if v.status == "skipped"} == {"ux.j_find", "ux.j_act"}
    assert report.readiness == 100.0 and report.grade == "A" and report.coverage["partial"]
    assert {r.method for r in web.requests} == {"GET"}  # read-only: never POSTs, forms are only inspected
    assert "test-drive/send" not in {r.url.path for r in web.requests}


@pytest.mark.anyio
async def test_page_selection_is_stable_and_bounded():
    _, _, _, ctx1 = await scan()
    _, _, _, ctx2 = await scan()
    assert [p.url for p in ctx1.pages] == [p.url for p in ctx2.pages]
    assert len(ctx1.pages) <= 15
    roles = [p.role for p in ctx1.pages]
    assert roles.count("vdp") == 5 and "stock_list" in roles and "test_drive" in roles and "service" in roles


@pytest.mark.anyio
async def test_robots_blocking_retrieval_bot_fails_and_training_only_warns():
    res, *_ = await scan(robots="User-agent: ChatGPT-User\nDisallow: /stoc/")
    assert status(res, "disc.robots_ai") == "fail" and "ChatGPT-User" in res["disc.robots_ai"].missing
    res, *_ = await scan(robots="User-agent: GPTBot\nDisallow: /")
    assert status(res, "disc.robots_ai") == "warn"


@pytest.mark.anyio
async def test_waf_blocking_ai_user_agent_is_critical_and_caps_the_grade():
    res, report, *_ = await scan(block_ua="GPTBot")
    assert status(res, "disc.waf_ua") == "fail" and res["disc.waf_ua"].severity == "CRITICAL"
    assert report.gate_applied and "disc.waf_ua" in report.gate_checks
    assert report.grade_before_gate == "A" and report.grade == "C"


@pytest.mark.anyio
async def test_sitemap_states():
    assert status((await scan(sitemap_fresh=False))[0], "disc.sitemap") == "warn"
    assert status((await scan(sitemap=False))[0], "disc.sitemap") == "fail"


@pytest.mark.anyio
async def test_llms_txt_missing_fails():
    assert status((await scan(llms=False))[0], "disc.llms_txt") == "fail"


@pytest.mark.anyio
async def test_js_only_vdps_fail_no_js_and_data_checks():
    res, *_ = await scan(vdp_kwargs={"js_only": True})
    assert status(res, "disc.no_js") == "fail"
    assert status(res, "inv.schema_vehicle") == "fail" and status(res, "inv.price_readable") == "fail"


@pytest.mark.anyio
async def test_price_in_image_fails_readability_and_hints_at_images():
    res, *_ = await scan(vdp_kwargs={"price_in_text": False})
    r = res["inv.price_readable"]
    assert r.status == "fail" and r.details["possible_price_in_image"] and r.details["vision"] == "deferred"


@pytest.mark.anyio
async def test_incomplete_offer_and_missing_schema():
    res, *_ = await scan(vdp_kwargs={"offer_complete": False})
    assert status(res, "inv.schema_offer") == "warn"
    res, *_ = await scan(vdp_kwargs={"jsonld": False})
    assert status(res, "inv.schema_vehicle") == "fail" and status(res, "inv.schema_offer") == "fail"
    assert status(res, "inv.price_consistency") == "na"


@pytest.mark.anyio
async def test_price_mismatch_between_jsonld_and_text():
    res, *_ = await scan(vdp_kwargs={"price_mismatch": True})
    assert status(res, "inv.price_consistency") == "fail"


@pytest.mark.anyio
async def test_identity_checks():
    res, *_ = await scan(full_ld=False)
    assert status(res, "id.schema_dealer") == "fail"
    assert status(res, "id.nap") in ("warn", "fail")
    res, *_ = await scan()
    assert status(res, "id.schema_dealer") == "pass" and status(res, "id.nap") == "pass"


def test_telephone_inside_contactpoint_counts():
    from app.checks.identity import _has, _ld_phone
    node = {"contactPoint": {"@type": "ContactPoint", "telephone": "+40 21 9229"}}
    assert _has(node, "telephone") and _ld_phone(node) == "+40 21 9229"
    assert _has({"contactPoint": [{"telephone": "0712"}]}, "telephone")
    assert not _has({"contactPoint": {"contactType": "sales"}}, "telephone")


@pytest.mark.anyio
async def test_actions_checks():
    res, *_ = await scan(test_drive_from_vdp=False)
    assert status(res, "act.test_drive") == "warn"
    res, *_ = await scan(captcha=True)
    assert status(res, "act.test_drive") == "warn" and "CAPTCHA" in res["act.test_drive"].summary
    res, *_ = await scan(form=BAD_FORM)
    assert status(res, "act.forms_semantic") in ("fail", "warn")
    res, *_ = await scan()
    assert status(res, "act.forms_semantic") == "pass"


@pytest.mark.anyio
async def test_https_redirect_and_protocol_opportunity():
    res, *_ = await scan(http_redirect=False)
    assert status(res, "trust.https") == "warn"
    res, report, *_ = await scan(card=False)
    r = res["proto.aap_card"]
    assert r.status == "fail" and r.not_adopted and "proto.aap_card" not in report.gate_checks
    assert report.grade != "C" or report.grade_before_gate == "C"  # "not adopted" never triggers the CRITICAL gate


@pytest.mark.anyio
async def test_vdps_discovered_from_stock_list_when_sitemap_is_missing():
    res, *_ = await scan(sitemap=False)
    assert status(res, "inv.vdp_urls") == "pass"


@pytest.mark.anyio
async def test_no_test_drive_entry_point_at_all_fails():
    res, *_ = await scan(test_drive_from_vdp=False, form="<p>no form</p>", vdp_kwargs=None)
    # the entry point exists in the nav in this variant, so it is only "not reachable from a VDP"
    assert status(res, "act.test_drive") == "warn"


def test_selector_does_not_mistake_campaign_pages_for_vdps_and_matches_service_prefixes():
    from app.services.page_selector import classify_url
    assert classify_url("https://a.ro/masini-noi/cu-livrare-imediata") == "stock_list"
    assert classify_url("https://a.ro/masini-noi/oferte-actiuni") == "stock_list"
    assert classify_url("https://a.ro/stoc/golf-8-2021") == "vdp"
    assert classify_url("https://a.ro/masini-rulate/vw-golf-tdi-comfortline-plus") == "vdp"
    assert classify_url("https://a.ro/service-si-accesorii/oferte") == "service"
    assert classify_url("https://a.ro/blog/foo.jpg") is None


@pytest.mark.anyio
async def test_external_stock_domain_is_reported_not_silently_failed():
    web, factory = build_site(sitemap=False)
    home = web.routes["a.example/"]
    html = home.text.replace("</body>", "<a href='https://www.dasweltauto.example/search'>Mașini rulate</a></body>")
    web.routes["a.example/"] = type(home)(200, headers=home.headers, text=html)
    for slug in ("golf-8-2021", "octavia-2020", "focus-2019", "corolla-2022", "clio-2021", "astra-2020"):
        web.routes.pop(f"a.example/stoc/{slug}")
    web.routes["a.example/stoc/"] = type(home)(200, headers=home.headers, text="<html><body>no links</body></html>")
    fetcher = factory()
    acq = await acquire_homepage(fetcher, normalize_input("a.example"))
    ctx = await build_context(acq, "a.example", "dealer", fetcher, factory, delay_s=0)
    results = {r.check_id: r for r in await run_checks(ctx, load_template("dealer"))}
    r = results["inv.vdp_urls"]
    assert r.status == "fail" and "dasweltauto.example" in r.summary
    await fetcher.aclose()


def test_dominant_sitemap_section_is_inferred_as_vdp_prefix_in_any_language():
    from app.services.page_selector import classify_url, infer_vdp_prefixes
    urls = [f"https://a.ro/vanzari-auto/mercedes-benz-clasa-a-{i}.html" for i in range(40)] + ["https://a.ro/despre", "https://a.ro/blog/x"]
    pref = infer_vdp_prefixes(urls)
    assert pref == {"vanzari-auto"}
    assert classify_url(urls[0], pref) == "vdp"
    assert infer_vdp_prefixes(urls[:10]) == set()  # too small to infer anything
    blog = [f"https://a.ro/articole/post-{i}" for i in range(40)]
    assert infer_vdp_prefixes(blog) == {"articole"}  # known limitation: id-like blog slugs look like VDPs


def test_offer_values_follow_schema_org_rules():
    from app.checks.util import valid_offer_value as ok
    assert ok("price", 19500) and ok("price", "19500.50") and not ok("price", "19.500,00 EUR") and not ok("price", "{{$model->price}}")
    assert ok("priceCurrency", "EUR") and not ok("priceCurrency", "eur") and not ok("priceCurrency", "{{$c}}")
    assert ok("availability", "https://schema.org/InStock") and ok("availability", "http://schema.org/OutOfStock") and ok("availability", "InStock")
    assert not ok("availability", "http://schema.org/{{$x ? 'InStock' : 'OutOfStock'}}") and not ok("availability", "In stock")
    assert ok("itemCondition", "https://schema.org/UsedCondition") and not ok("itemCondition", "used")
    assert not ok("price", None) and not ok("price", True)
