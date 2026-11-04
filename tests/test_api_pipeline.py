import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.config import settings
from app.jobs.scan_pipeline import Deps
from app.main import create_app
from app.repo.db import make_engine
from app.repo.models import Scan, Site
from app.services.crawler import SafeFetcher
from app.services.meta_llm import MetaLlm
from tests.conftest import FakeWeb, html_page, public_resolver, read_fixture

TXT = {"content-type": "text/plain"}


def make_client(routes, *, llm=None, renderer=None, run_checks=False):
    web = FakeWeb(routes)
    deps = Deps(
        fetcher_factory=lambda **kw: SafeFetcher(transport=web.transport, resolver=public_resolver, **kw),
        llm_factory=lambda: llm,
        renderer=renderer,
        run_checks=run_checks,
    )
    engine = make_engine("sqlite:///:memory:")
    app = create_app(engine=engine, deps=deps)
    return TestClient(app), web, engine


def scan(client, url="a.example", **extra):
    r = client.post("/api/scans", json={"url": url, **extra})
    assert r.status_code in (202, 422, 429), r.text
    return r


def result(client, r):
    return client.get(f"/api/scans/{r.json()['scan_id']}").json()


def test_dealer_end_to_end():
    c, web, engine = make_client({"a.example/": html_page(read_fixture("dealer-lite.html"))})
    with c:
        r = scan(c)
        assert r.status_code == 202 and r.json()["status"] == "queued"
        out = result(c, r)
        assert out["status"] == "classified"
        assert out["site"]["type"] == "dealer"
        cls = out["classification"]
        assert cls["type"] == "dealer" and cls["method"] == "deterministic" and not cls["needs_confirmation"]
        assert cls["language"] == "ro" and cls["evidence"] and cls["version"] == "step0-3"
        with Session(engine) as s:
            assert [e["kind"] for e in s.exec(select(Scan)).one().fetch_log] == ["robots", "homepage", "sitemap"]
    assert {r.method for r in web.requests} == {"GET"}


def test_invalid_and_private_inputs_rejected_synchronously():
    c, web, _ = make_client({})
    with c:
        for bad in ("", "localhost", "http://127.0.0.1", "ftp://x.com", "10.0.0.1"):
            r = scan(c, bad)
            assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_URL"
        assert c.post("/api/scans", json={"url": "a.example", "type_hint": "banana"}).status_code == 422
    assert web.requests == []


def test_ambiguous_site_requires_confirmation_then_confirm():
    c, _, _ = make_client({"a.example/": html_page(read_fixture("ambiguous.html"))})
    with c:
        r = scan(c)
        out = result(c, r)
        assert out["status"] == "needs_confirmation" and out["site"]["type"] is None
        assert out["classification"]["needs_confirmation"] and len(out["classification"]["alternatives"]) == 2
        sid = r.json()["scan_id"]
        ok = c.post(f"/api/scans/{sid}/confirm", json={"type": "dealer"})
        assert ok.status_code == 200
        body = ok.json()
        assert body["status"] == "classified" and body["site"]["type"] == "dealer"
        assert body["classification"]["confirmed_by_user"] is True
        again = c.post(f"/api/scans/{sid}/confirm", json={"type": "dealer"})
        assert again.status_code == 409
        assert c.post(f"/api/scans/{sid}/confirm", json={"type": "nope"}).status_code == 422
        assert c.post("/api/scans/999/confirm", json={"type": "dealer"}).status_code == 404


def test_confirm_rejected_when_not_awaiting():
    c, _, _ = make_client({"a.example/": html_page(read_fixture("dealer-lite.html"))})
    with c:
        sid = scan(c).json()["scan_id"]
        assert c.post(f"/api/scans/{sid}/confirm", json={"type": "importer"}).status_code == 409


def test_non_auto_site_is_unsupported():
    c, _, _ = make_client({"a.example/": html_page(read_fixture("non-auto-blog.html"))})
    with c:
        out = result(c, scan(c))
        assert out["status"] == "classified" and out["site"]["type"] == "unsupported"


@pytest.mark.parametrize(
    "routes,code",
    [
        ({"a.example/": html_page("no", 403)}, "BLOCKED_BY_WAF"),
        ({"a.example/": (200, {"content-type": "image/png"}, "x")}, "NOT_HTML"),
        ({"a.example/": (302, {"location": "http://169.254.169.254/"}, "")}, "BLOCKED_TARGET"),
    ],
)
def test_failures_are_typed(routes, code):
    c, _, _ = make_client(routes)
    with c:
        out = result(c, scan(c))
        assert out["status"] == "failed" and out["error"]["code"] == code


def test_robots_blocking_us_gives_a_partial_report_not_a_failure():
    robots = "User-agent: ChatGPT-User\nAllow: /\n\nUser-agent: GPTBot\nDisallow: /\n\nUser-agent: *\nDisallow: /"
    c, web, _ = make_client({"a.example/robots.txt": (200, TXT, robots), "a.example/": html_page("<html>home</html>")})
    with c:
        out = result(c, scan(c))
        assert out["status"] == "completed" and out["error"] is None and out["score"] is None
        rep = out["report"]
        assert rep["partial"] is True and rep["reason"] == "BLOCKED_BY_ROBOTS" and "not_evaluated" in rep
        agents = {a["agent"]: a["allowed"] for a in rep["robots"]["agents"]}
        assert agents["ChatGPT-User"] is True and agents["GPTBot"] is False and agents["Claude-User"] is False  # unnamed -> the * group
        assert rep["robots"]["scanner"]["allowed"] is False and rep["robots"]["unlisted_agents_allowed"] is False
        assert rep["robots"]["verdict"]["status"] == "fail" and "Claude-User" in rep["robots"]["verdict"]["blocked_user_facing"]
        assert not [r for r in web.requests if r.url.path == "/"]  # the pages themselves were not fetched
        assert c.get("/api/leaderboard").json()["entries"] == []  # no score, no ranking
        row = c.get("/api/scans").json()["scans"][0]
        assert row["partial"] is True and row["ax_score"] is None


def test_scan_ignoring_robots_reads_the_site_and_says_so():
    c, web, _ = make_client({"a.example/robots.txt": (200, TXT, "User-agent: *\nDisallow: /"), "a.example/": html_page(read_fixture("dealer-lite.html"))})
    with c:
        out = result(c, c.post("/api/scans", json={"url": "a.example", "ignore_robots": True}))
        assert out["ignore_robots"] is True and out["status"] in ("classified", "needs_confirmation", "completed")
        assert out["classification"] and not (out["report"] or {}).get("partial")
        assert any(r.url.path == "/" for r in web.requests)  # the homepage was fetched although robots.txt disallows it


def test_the_override_can_be_switched_off_by_the_server(monkeypatch):
    monkeypatch.setattr(settings, "allow_ignore_robots", False)
    c, _, _ = make_client({"a.example/": html_page("x")})
    with c:
        r = c.post("/api/scans", json={"url": "a.example", "ignore_robots": True})
        assert r.status_code == 403 and r.json()["error"]["code"] == "ROBOTS_OVERRIDE_DISABLED"
        assert c.get("/health").json()["ignore_robots_allowed"] is False


def test_robots_override_semantics_and_old_databases_get_the_new_column(tmp_path):
    from sqlalchemy import create_engine, inspect, text
    from app.repo.db import init_db
    from app.services.crawler import Robots

    rb = Robots("User-agent: *\nDisallow: /\nUser-agent: GPTBot\nAllow: /")
    assert rb.allowed("https://a.example/") is False and rb.allowed("https://a.example/", user_agent="Claude-User") is False
    rb.ignore = True
    assert rb.allowed("https://a.example/") is True  # our scanner: waived on request
    assert rb.allowed("https://a.example/", user_agent="Claude-User") is False  # the analysis of other agents stays truthful
    assert rb.allowed("https://a.example/", user_agent="GPTBot") is True

    eng = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with eng.begin() as conn:  # a database created before the column existed
        conn.execute(text("CREATE TABLE scan (id INTEGER PRIMARY KEY, site_id INTEGER, status VARCHAR)"))
        conn.execute(text("INSERT INTO scan (site_id, status) VALUES (1, 'completed')"))
    init_db(eng)
    assert "ignore_robots" in {c["name"] for c in inspect(eng).get_columns("scan")}
    with eng.begin() as conn:
        assert conn.execute(text("SELECT ignore_robots FROM scan")).scalar() in (0, False)
    init_db(eng)  # running it twice is harmless


def test_timeout_is_reported(monkeypatch):
    monkeypatch.setattr(settings, "step0_budget_s", 0.05)

    async def slow(request):
        await asyncio.sleep(0.5)
        return html_page("x")

    deps = Deps(
        fetcher_factory=lambda **kw: SafeFetcher(transport=httpx.MockTransport(slow), resolver=public_resolver, **kw),
        llm_factory=lambda: None,
        renderer=None,
        run_checks=False,
    )
    app = create_app(engine=make_engine("sqlite:///:memory:"), deps=deps)
    with TestClient(app) as c:
        out = result(c, scan(c))
        assert out["status"] == "failed" and out["error"]["code"] == "TIMEOUT"


def test_cache_reuse_and_force():
    c, web, _ = make_client({"a.example/": html_page(read_fixture("dealer-lite.html"))})
    with c:
        first = result(c, scan(c))
        n = len(web.requests)
        second = result(c, scan(c))
        assert second["id"] != first["id"] and second["classification"]["from_cache"] is True
        assert len(web.requests) == n
        third = result(c, scan(c, force=True))
        assert len(web.requests) > n and "from_cache" not in third["classification"]


def test_canonical_origin_merges_www_alias():
    routes = {
        "a.example/": (301, {"location": "https://www.a.example/"}, ""),
        "www.a.example/": html_page(read_fixture("dealer-lite.html")),
    }
    c, _, engine = make_client(routes)
    with c:
        out = result(c, scan(c))
        assert out["site"]["origin"] == "https://www.a.example"
        out2 = result(c, scan(c, "www.a.example"))
        assert out2["classification"]["from_cache"] is True
        with Session(engine) as s:
            assert len(s.exec(select(Site)).all()) == 1


def test_js_shell_uses_renderer_fallback():
    rendered = read_fixture("dealer-lite.html")

    async def renderer(url):
        return rendered

    c, _, _ = make_client({"a.example/": html_page(read_fixture("js-shell.html"))}, renderer=renderer)
    with c:
        out = result(c, scan(c))
        assert out["classification"]["js_rendered"] is True and out["site"]["type"] == "dealer"


def test_js_shell_without_renderer_asks_for_confirmation():
    c, _, _ = make_client({"a.example/": html_page(read_fixture("js-shell.html"))})
    with c:
        out = result(c, scan(c))
        assert out["status"] == "needs_confirmation" and out["classification"]["js_rendered"] is False


def llm_returning(obj, status=200):
    def handler(req):
        return httpx.Response(status, json={"choices": [{"message": {"content": json.dumps(obj)}}]})

    return MetaLlm(api_key="k", base_url="https://api.test/v1", transport=httpx.MockTransport(handler))


def test_pipeline_combines_llm_and_heuristic():
    llm = llm_returning({"type": "dealer", "confidence": 0.9, "brands": ["Skoda"], "evidence": []})
    c, _, _ = make_client({"a.example/": html_page(read_fixture("dealer-lite.html"))}, llm=llm)
    with c:
        cls = result(c, scan(c))["classification"]
        assert cls["method"] == "deterministic+llm" and cls["llm"]["type"] == "dealer"
        assert "Skoda" in cls["brands"]


def test_llm_outage_degrades_to_deterministic():
    llm = llm_returning({}, status=500)
    c, _, _ = make_client({"a.example/": html_page(read_fixture("dealer-lite.html"))}, llm=llm)
    with c:
        out = result(c, scan(c))
        assert out["status"] == "classified" and out["classification"]["method"] == "deterministic"


def test_llm_disagreement_triggers_confirmation():
    llm = llm_returning({"type": "importer", "confidence": 0.7})
    c, _, _ = make_client({"a.example/": html_page(read_fixture("dealer-lite.html"))}, llm=llm)
    with c:
        assert result(c, scan(c))["status"] == "needs_confirmation"


def test_rate_limit(monkeypatch):
    c, _, _ = make_client({"a.example/": html_page(read_fixture("dealer-lite.html"))})
    c.app.state.limiter.per_minute = 2
    with c:
        assert scan(c).status_code == 202
        assert scan(c).status_code == 202
        r = scan(c)
        assert r.status_code == 429 and r.json()["error"]["code"] == "RATE_LIMITED"


def test_unknown_scan_404_and_health():
    c, _, _ = make_client({})
    with c:
        assert c.get("/api/scans/12345").status_code == 404
        assert c.get("/health").json()["ok"] is True


def test_marketplace_end_to_end_and_confirm_accepts_marketplace():
    c, _, _ = make_client({"a.example/": html_page(read_fixture("marketplace-lite.html"))})
    with c:
        out = result(c, scan(c))
        assert out["status"] == "classified" and out["site"]["type"] == "marketplace"
    c, _, _ = make_client({"a.example/": html_page(read_fixture("ambiguous.html"))})
    with c:
        sid = scan(c).json()["scan_id"]
        ok = c.post(f"/api/scans/{sid}/confirm", json={"type": "marketplace"})
        assert ok.status_code == 200 and ok.json()["site"]["type"] == "marketplace"
        assert scan(c, type_hint="marketplace").status_code == 202


def test_full_scan_end_to_end_with_checks():
    from tests.site_builder import build_site
    web, factory = build_site()
    deps = Deps(fetcher_factory=factory, llm_factory=lambda: None, renderer=None, run_checks=True)
    app = create_app(engine=make_engine("sqlite:///:memory:"), deps=deps)
    with TestClient(app) as c:
        out = result(c, scan(c))
        assert out["status"] == "completed", out
        assert out["classification"]["type"] == "dealer"
        assert out["score"]["grade"] == "A" and out["score"]["ax_score"] == 100.0
        rep = out["report"]
        assert rep["coverage"]["partial"] and {l["layer"] for l in rep["layers"]} >= {"discovery", "data", "protocol"}
        assert all("check_id" in x and "status" in x for x in rep["results"])
    assert {r.method for r in web.requests} == {"GET"}


def test_non_dealer_types_are_failed_as_unsupported_with_checks_enabled():
    from tests.site_builder import build_site  # noqa: F401
    deps = Deps(fetcher_factory=lambda **kw: SafeFetcher(transport=FakeWeb({"a.example/": html_page(read_fixture("marketplace-lite.html"))}).transport, resolver=public_resolver, **kw),
                llm_factory=lambda: None, renderer=None, run_checks=True)
    app = create_app(engine=make_engine("sqlite:///:memory:"), deps=deps)
    with TestClient(app) as c:
        out = result(c, scan(c))
        assert out["status"] == "failed" and out["error"]["code"] == "TYPE_NOT_SUPPORTED"
        assert out["report"] is None and out["score"] is None


def test_confirming_a_dealer_triggers_the_checks():
    from tests.site_builder import build_site
    web, factory = build_site()
    # make the homepage ambiguous so Step 0 asks for confirmation, then confirm as dealer
    web.routes["a.example/"] = html_page(read_fixture("ambiguous.html"))
    deps = Deps(fetcher_factory=factory, llm_factory=lambda: None, renderer=None, run_checks=True)
    app = create_app(engine=make_engine("sqlite:///:memory:"), deps=deps)
    with TestClient(app) as c:
        sid = scan(c).json()["scan_id"]
        assert c.get(f"/api/scans/{sid}").json()["status"] == "needs_confirmation"
        assert c.post(f"/api/scans/{sid}/confirm", json={"type": "dealer"}).status_code == 200
        done = c.get(f"/api/scans/{sid}").json()
        assert done["status"] == "completed" and done["report"]["site_type"] == "dealer"


def test_list_scans_returns_summaries_newest_first():
    c, _, _ = make_client({"a.example/": html_page(read_fixture("dealer-lite.html")), "b.example/": html_page(read_fixture("dealer-lite.html"))})
    with c:
        for u in ("a.example", "b.example"):
            c.post("/api/scans", json={"url": u})
        items = c.get("/api/scans?limit=10").json()["scans"]
    assert [i["domain"] for i in items][:2] == ["b.example", "a.example"]
    assert {"id", "status", "ax_score", "grade", "fixes_count", "checks", "created_at"} <= set(items[0])


def test_leaderboard_uses_latest_completed_scan_per_domain():
    from sqlmodel import Session
    from app.repo.models import Scan, Site
    c, _, engine = make_client({})
    with c:
        pass
    with Session(engine) as s:
        a = Site(domain="a.example", canonical_origin="https://a.example", type="dealer")
        b = Site(domain="b.example", canonical_origin="https://b.example", type="dealer")
        s.add(a); s.add(b); s.commit(); s.refresh(a); s.refresh(b)
        s.add(Scan(site_id=a.id, status="completed", ax_score=80, grade="B"))  # old, better
        s.add(Scan(site_id=a.id, status="completed", ax_score=30, grade="F"))  # latest -> counts
        s.add(Scan(site_id=a.id, status="failed"))                              # ignored
        s.add(Scan(site_id=b.id, status="completed", ax_score=50, grade="D"))
        s.commit()
    rows = c.get("/api/leaderboard").json()["entries"]
    assert [(r["rank"], r["domain"], r["ax_score"]) for r in rows] == [(1, "b.example", 50), (2, "a.example", 30)]
    assert c.get("/api/leaderboard?type=importer").json()["entries"] == []


def test_interrupted_scans_are_failed_on_startup():
    from sqlmodel import Session
    from app.jobs.scan_pipeline import fail_interrupted
    from app.repo.models import Scan, Site
    c, _, engine = make_client({})
    with c:
        pass  # init_db
    with Session(engine) as s:
        site = Site(domain="x.example", canonical_origin="https://x.example")
        s.add(site); s.commit(); s.refresh(site)
        s.add(Scan(site_id=site.id, status="scanning")); s.add(Scan(site_id=site.id, status="needs_confirmation")); s.commit()
    assert fail_interrupted(engine) == 1
    with Session(engine) as s:
        got = {x.status: x.error_code for x in s.exec(__import__("sqlmodel").select(Scan)).all()}
    assert got == {"failed": "INTERRUPTED", "needs_confirmation": None}


def test_unsupported_type_is_failed_with_clear_message():
    import asyncio
    from sqlmodel import Session
    from app.jobs.scan_pipeline import Deps, fail_interrupted, maybe_run_checks
    from app.repo.models import Scan, Site
    c, _, engine = make_client({})
    with c:
        pass
    with Session(engine) as s:
        site = Site(domain="market.example", canonical_origin="https://market.example", type="marketplace")
        s.add(site); s.commit(); s.refresh(site)
        s.add(Scan(site_id=site.id, status="classified", classification={"type": "marketplace"}))
        s.add(Scan(site_id=site.id, status="classified", classification={"type": "marketplace"}))
        s.commit()
    deps = Deps(fetcher_factory=lambda **kw: None, llm_factory=lambda: None, renderer=None, run_checks=True)
    asyncio.run(maybe_run_checks(1, engine, deps))
    with Session(engine) as s:
        sc = s.get(Scan, 1)
        assert (sc.status, sc.error_code) == ("failed", "TYPE_NOT_SUPPORTED")
        assert sc.error_message == "Detected as marketplace. This version scores dealer, brand/importer and online-shop sites."
    assert fail_interrupted(engine) == 1  # the sweep catches the one still parked
    with Session(engine) as s:
        assert s.get(Scan, 2).error_code == "TYPE_NOT_SUPPORTED"


def test_scan_refused_without_api_key(monkeypatch):
    from app.config import settings
    from app.jobs.scan_pipeline import Deps
    from app.main import create_app
    from app.repo.db import make_engine
    from fastapi.testclient import TestClient
    monkeypatch.setattr(settings, "meta_api_key", "")
    with TestClient(create_app(make_engine("sqlite://"), Deps())) as c:
        assert c.get("/health").json()["llm_configured"] is False
        r = c.post("/api/scans", json={"url": "a.example"})
        assert r.status_code == 503 and r.json()["error"]["code"] == "LLM_NOT_CONFIGURED"


def test_daily_scan_cap_stops_new_scans(monkeypatch):
    from app.config import settings
    from app.jobs.scan_pipeline import Deps

    class _Llm:
        async def aclose(self):
            pass

    monkeypatch.setattr(settings, "max_scans_per_day", 1)
    engine = make_engine("sqlite:///:memory:")
    app = create_app(engine=engine, deps=Deps(run_checks=False, llm_factory=lambda: None))
    with TestClient(app) as c:
        assert c.post("/api/scans", json={"url": "a.example"}).status_code == 202
        r = c.post("/api/scans", json={"url": "b.example"})
        assert r.status_code == 429 and r.json()["error"]["code"] == "DAILY_LIMIT"


def test_sqlite_folder_is_created_when_missing(tmp_path):
    db = tmp_path / "not" / "there" / "ax.db"
    eng = make_engine(f"sqlite:///{db.as_posix()}")
    from app.repo.db import init_db
    init_db(eng)
    assert db.exists()
