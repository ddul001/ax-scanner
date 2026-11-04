import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.checks.context import build_context
from app.checks.engine import load_template, make_report, run_checks
from app.fixes.jsonld import generate_fixes, snippet, validate
from app.fixes.engine import generate_all
from app.jobs.scan_pipeline import Deps, _store_fixes
from app.main import create_app
from app.repo.db import make_engine
from app.repo.models import Fix, Scan, Site
from app.services.crawler import acquire_homepage
from app.services.url_normalizer import normalize_input
from tests.site_builder import build_site


async def scan(**kw):
    web, factory = build_site(**kw)
    fetcher = factory()
    acq = await acquire_homepage(fetcher, normalize_input("a.example"))
    ctx = await build_context(acq, "a.example", "dealer", fetcher, factory, delay_s=0)
    template = load_template("dealer")
    results = await run_checks(ctx, template)
    await fetcher.aclose()
    return ctx, template, results


@pytest.mark.anyio
async def test_good_site_needs_no_fixes():
    ctx, t, results = await scan()
    assert generate_fixes(ctx, results, t["weights"]) == []


@pytest.mark.anyio
async def test_vehicle_fix_builds_valid_car_and_offer_from_page_facts():
    ctx, t, results = await scan(vdp_kwargs={"jsonld": False})
    fixes = generate_fixes(ctx, results, t["weights"], ["Toyota"])
    cars = [f for f in fixes if f.check_id == "inv.schema_vehicle"]
    assert cars and all(f.errors == [] for f in cars)
    node = cars[0].jsonld
    assert node["@type"] == "Car" and node["url"].startswith("https://a.example/")
    assert node["offers"]["@type"] == "Offer" and node["offers"]["priceCurrency"] in ("EUR", "RON")
    assert node["offers"]["availability"].endswith("InStock")
    assert cars[0].est_gain > 0 and cars[0].assumptions
    assert validate(node) == []


@pytest.mark.anyio
async def test_dealer_fix_uses_page_facts_and_invents_nothing():
    ctx, t, results = await scan(full_ld=False)
    d = next(f for f in generate_fixes(ctx, results, t["weights"]) if f.check_id == "id.schema_dealer")
    assert d.jsonld["@type"] == "AutoDealer" and d.jsonld["name"] == "AutoPrima Cluj"
    assert d.jsonld["telephone"] == "+40264000100"
    assert not ({"address", "geo", "openingHours"} & set(d.jsonld))  # not exposed as data -> listed in todo, not made up
    assert {"address (PostalAddress)", "geo coordinates", "opening hours"} <= set(d.todo)


def test_validate_catches_bad_nodes():
    bad = {"@context": "https://schema.org", "@type": "Car", "name": "x", "url": "/rel",
           "offers": {"@type": "Offer", "price": "abc", "priceCurrency": "euro"}}
    errs = validate(bad)
    assert any("absolute" in e for e in errs) and any("numeric" in e for e in errs) and any("ISO 4217" in e for e in errs)


def test_snippet_cannot_break_out_of_script_tag():
    s = snippet({"@context": "https://schema.org", "@type": "Car", "name": "</script><b>x"})
    assert s.count("</script>") == 1


@pytest.mark.anyio
async def test_api_approve_gate_and_export():
    ctx, t, results = await scan(vdp_kwargs={"jsonld": False})
    engine = make_engine("sqlite:///:memory:")
    app = create_app(engine=engine, deps=Deps(run_checks=False))
    with TestClient(app) as c:
        with Session(engine) as s:
            site = Site(domain="a.example", canonical_origin="https://a.example")
            s.add(site); s.commit(); s.refresh(site)
            scan_row = Scan(site_id=site.id, status="completed")
            s.add(scan_row); s.commit(); s.refresh(scan_row)
            _store_fixes(s, scan_row, await generate_all(ctx, results, t["weights"]))
            s.commit()
            sid = scan_row.id
        r = c.get(f"/api/scans/{sid}/export")
        assert r.status_code == 409 and r.json()["error"]["code"] == "NO_APPROVED_FIXES"
        fixes = c.get(f"/api/scans/{sid}/fixes").json()
        assert fixes["fixes"] and fixes["total_est_gain"] > 0
        assert {f["status"] for f in fixes["fixes"]} == {"proposed"}
        assert c.get(f"/api/scans/{sid}").json()["fixes_count"] == len(fixes["fixes"]) > 0
        fid = fixes["fixes"][0]["id"]
        assert c.post(f"/api/fixes/{fid}/approve").json()["status"] == "approved"
        out = c.get(f"/api/scans/{sid}/export").json()
        paths = [f["path"] for f in out["files"]]
        assert paths[0].startswith("jsonld/01-") and "snippets.html" in paths and "README.md" in paths
        assert sum(p.startswith("jsonld/") for p in paths) == 1  # only the approved fix is exported
        assert c.post("/api/fixes/9999/approve").status_code == 404
    with Session(engine) as s:
        assert s.exec(select(Fix).where(Fix.id == fid)).one().status == "exported"


@pytest.mark.anyio
async def test_reject_excludes_fix_from_gain_and_export():
    ctx, t, results = await scan(vdp_kwargs={"jsonld": False})
    engine = make_engine("sqlite:///:memory:")
    app = create_app(engine=engine, deps=Deps(run_checks=False))
    with TestClient(app) as c:
        with Session(engine) as s:
            site = Site(domain="a.example", canonical_origin="https://a.example")
            s.add(site); s.commit(); s.refresh(site)
            row = Scan(site_id=site.id, status="completed")
            s.add(row); s.commit(); s.refresh(row)
            _store_fixes(s, row, await generate_all(ctx, results, t["weights"]))
            s.commit()
            sid = row.id
        before = c.get(f"/api/scans/{sid}/fixes").json()
        fid = before["fixes"][0]["id"]
        gain = before["fixes"][0]["est_gain"]
        assert c.post(f"/api/fixes/{fid}/approve").json()["status"] == "approved"
        assert c.post(f"/api/fixes/{fid}/reject").json()["status"] == "rejected"
        after = c.get(f"/api/scans/{sid}/fixes").json()
        assert round(before["total_est_gain"] - after["total_est_gain"], 1) == round(gain, 1)
        assert c.get(f"/api/scans/{sid}/export").status_code == 409  # rejected is not exported
        assert c.post(f"/api/fixes/{fid}/approve").json()["status"] == "approved"  # can be reconsidered
        assert c.get(f"/api/scans/{sid}/export").status_code == 200
        assert c.post(f"/api/fixes/{fid}/reject").status_code == 409  # exported is final
        assert c.post("/api/fixes/9999/reject").status_code == 404


def _page(body: str, ld: str = "") -> "Page":
    from app.checks.context import Page
    script = f'<script type="application/ld+json">{ld}</script>' if ld else ""
    return Page(url="https://x.example/p", role="vdp", status=200, html=f"<html><body><h1>T</h1>{body}{script}</body></html>")


def test_unrendered_template_values_are_dropped_not_copied():
    from app.fixes.jsonld import _scrub, build_vehicle
    dropped: list[str] = []
    clean = _scrub({"offers": {"price": "{{$model->price}}", "priceCurrency": "EUR", "url": "{{url()->full()}}"}}, dropped)
    assert clean == {"offers": {"priceCurrency": "EUR"}} and dropped == ["offers.price", "offers.url"]
    ld = '{"@type":"Product","name":"X","offers":{"@type":"Offer","price":"{{$p}}","priceCurrency":"{{$c}}"}}'
    d = build_vehicle(_page("<p>Audi A4 2021 diesel automat 120.000 km 140 CP 19.500 EUR</p>", ld), ["Audi"])
    assert "{{" not in d.content and any("template code" in a for a in d.assumptions)
    assert d.jsonld["offers"]["price"] == 19500 and d.jsonld["offers"]["priceCurrency"] == "EUR" and not d.errors


def test_accessory_pages_are_not_vehicles():
    from app.fixes.jsonld import _is_vehicle_page
    assert not _is_vehicle_page(_page("<p>Rucsac sport 25 L. Pret 149 RON</p>"))
    assert _is_vehicle_page(_page("<p>Golf 2019 diesel 90.000 km 115 CP</p>"))
    assert _is_vehicle_page(_page("<p>VIN WVWZZZ1KZAW123456</p>"))


class _FakeLlm:
    async def structured(self, system, user, model_cls, **kw):
        assert "a.example" in user  # the site context reaches the model
        return model_cls(prompt="You are helping me fix a.example.\nUse the code under Fix 1 below.")

    async def aclose(self):
        pass


@pytest.mark.anyio
@pytest.mark.parametrize("llm, source", [(_FakeLlm, "meta"), (lambda: None, "template")])
async def test_fix_prompt_has_context_code_and_footer(llm, source):
    ctx, t, results = await scan(vdp_kwargs={"jsonld": False})
    engine = make_engine("sqlite:///:memory:")
    app = create_app(engine=engine, deps=Deps(run_checks=False, llm_factory=llm))
    with TestClient(app) as c:
        with Session(engine) as s:
            site = Site(domain="a.example", canonical_origin="https://a.example", type="dealer")
            s.add(site); s.commit(); s.refresh(site)
            row = Scan(site_id=site.id, status="completed", ax_score=40, grade="D")
            s.add(row); s.commit(); s.refresh(row)
            _store_fixes(s, row, await generate_all(ctx, results, t["weights"]))
            s.commit()
            sid = row.id
        r = c.post(f"/api/scans/{sid}/fix-prompt")
        assert r.status_code == 200
        body = r.json()
        assert body["source"] == source and "a.example" in body["prompt"]
        assert "### Fix 1:" in body["prompt"] and "aivexia.ro" in body["prompt"]
        assert "application/ld+json" in body["prompt"] or "@context" in body["prompt"]
        assert c.post("/api/scans/9999/fix-prompt").status_code == 404
