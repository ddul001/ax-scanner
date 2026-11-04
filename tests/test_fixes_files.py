import pytest

from app.checks.context import build_context
from app.checks.discovery import llms_txt, robots_ai
from app.checks.engine import load_template, run_checks
from app.fixes.engine import generate_all
from app.fixes.files import llms_coverage
from app.services.crawler import Robots, acquire_homepage
from app.services.url_normalizer import normalize_input
from tests.site_builder import HOST, build_site

BLOCK = "User-agent: ChatGPT-User\nDisallow: /\n\nUser-agent: PerplexityBot\nDisallow: /stoc/\n\nUser-agent: GPTBot\nDisallow: /\n\nUser-agent: *\nDisallow: /admin/\nDisallow: /stoc/\nAllow: /"


async def run(web, factory):
    fetcher = factory()
    acq = await acquire_homepage(fetcher, normalize_input("a.example"))
    ctx = await build_context(acq, "a.example", "dealer", fetcher, factory, delay_s=0)
    t = load_template("dealer")
    results = await run_checks(ctx, t)
    out = {"ctx": ctx, "t": t, "results": results, "by": {r.check_id: r for r in results}, "fetcher": fetcher}
    return out


@pytest.mark.anyio
async def test_llms_fix_makes_the_check_pass_after_applying():
    web, factory = build_site(llms=False)
    o = await run(web, factory)
    assert o["by"]["disc.llms_txt"].status == "fail"
    fixes = await generate_all(o["ctx"], o["results"], o["t"]["weights"])
    d = next(f for f in fixes if f.type == "llms_txt")
    assert d.errors == [] and d.est_gain > 0 and d.content.startswith("# AutoPrima Cluj")
    assert llms_coverage(d.content) >= {"stock", "service"}
    web.routes[f"{HOST}/llms.txt"] = (200, {"content-type": "text/markdown"}, d.content)  # "publish" it
    o2 = await run(web, factory)
    assert o2["by"]["disc.llms_txt"].status == "pass"


@pytest.mark.anyio
async def test_llms_fix_extends_an_incomplete_file_without_losing_it():
    web, factory = build_site(llms=False)
    web.routes[f"{HOST}/llms.txt"] = (200, {"content-type": "text/markdown"}, "# Mine\n- [Stoc](https://a.example/stoc/)\n")
    o = await run(web, factory)
    assert o["by"]["disc.llms_txt"].status == "warn"
    d = next(f for f in await generate_all(o["ctx"], o["results"], o["t"]["weights"]) if f.type == "llms_txt")
    assert d.content.startswith("# Mine") and len(llms_coverage(d.content)) >= 2


@pytest.mark.anyio
async def test_robots_fix_unblocks_agents_keeps_other_rules_and_leaves_training_alone():
    web, factory = build_site(robots=BLOCK)
    o = await run(web, factory)
    assert o["by"]["disc.robots_ai"].status == "fail"
    d = next(f for f in await generate_all(o["ctx"], o["results"], o["t"]["weights"]) if f.type == "robots_txt")
    assert d.errors == [] and d.est_gain > 0
    new = Robots(d.content)
    assert new.allowed("https://a.example/stoc/x", user_agent="ChatGPT-User")
    assert new.allowed("https://a.example/stoc/x", user_agent="PerplexityBot")
    assert not new.allowed("https://a.example/admin/x", user_agent="PerplexityBot")  # unrelated rule kept
    assert not new.allowed("https://a.example/stoc/x", user_agent="GPTBot")  # training bot: policy choice, untouched
    assert any("Training crawlers" in a for a in d.assumptions)
    web.routes[f"{HOST}/robots.txt"] = (200, {"content-type": "text/plain"}, d.content)
    o2 = await run(web, factory)
    assert o2["by"]["disc.robots_ai"].status == "warn"  # only training crawlers still blocked


@pytest.mark.anyio
async def test_no_file_fixes_for_a_healthy_site_or_training_only_blocks():
    web, factory = build_site()
    o = await run(web, factory)
    assert await generate_all(o["ctx"], o["results"], o["t"]["weights"]) == []
    web, factory = build_site(robots="User-agent: GPTBot\nDisallow: /")
    o = await run(web, factory)
    assert o["by"]["disc.robots_ai"].status == "warn"
    assert not [f for f in await generate_all(o["ctx"], o["results"], o["t"]["weights"]) if f.type == "robots_txt"]


@pytest.mark.anyio
async def test_export_ships_root_files_under_their_real_names():
    from fastapi.testclient import TestClient
    from sqlmodel import Session

    from app.jobs.scan_pipeline import Deps, _store_fixes
    from app.main import create_app
    from app.repo.db import make_engine
    from app.repo.models import Scan, Site

    web, factory = build_site(llms=False, robots=BLOCK)
    o = await run(web, factory)
    drafts = await generate_all(o["ctx"], o["results"], o["t"]["weights"])
    engine = make_engine("sqlite:///:memory:")
    with TestClient(create_app(engine=engine, deps=Deps(run_checks=False))) as c:
        with Session(engine) as s:
            site = Site(domain="a.example", canonical_origin="https://a.example")
            s.add(site); s.commit(); s.refresh(site)
            sc = Scan(site_id=site.id, status="completed")
            s.add(sc); s.commit(); s.refresh(sc)
            _store_fixes(s, sc, drafts); s.commit()
            sid = sc.id
        for f in c.get(f"/api/scans/{sid}/fixes").json()["fixes"]:
            assert c.post(f"/api/fixes/{f['id']}/approve").status_code == 200
        paths = {f["path"]: f for f in c.get(f"/api/scans/{sid}/export").json()["files"]}
        assert {"llms.txt", "robots.txt", "README.md"} <= set(paths)
        assert paths["robots.txt"]["content"].startswith("User-agent:")
