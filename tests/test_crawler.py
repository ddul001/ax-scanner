import httpx
import pytest

from app.services.crawler import SafeFetcher, acquire_homepage, load_sitemap_urls
from app.services.url_normalizer import ScanError, normalize_input
from tests.conftest import FakeWeb, html_page, public_resolver, read_fixture

HOME = html_page(read_fixture("dealer-lite.html"))
TXT = {"content-type": "text/plain"}
XML = {"content-type": "application/xml"}


def fetcher(web, resolver=public_resolver):
    return SafeFetcher(transport=web.transport, resolver=resolver)


@pytest.mark.anyio
async def test_homepage_sitemap_and_only_get():
    web = FakeWeb({
        "a.example/robots.txt": (200, TXT, "User-agent: *\nDisallow: /admin\nSitemap: https://a.example/sm.xml"),
        "a.example/": HOME,
        "a.example/sm.xml": (200, XML, "<urlset><url><loc>https://a.example/stoc/1</loc></url></urlset>"),
    })
    f = fetcher(web)
    acq = await acquire_homepage(f, normalize_input("a.example"))
    urls = await load_sitemap_urls(f, acq)
    assert urls == ["https://a.example/stoc/1"]
    assert {r.method for r in web.requests} == {"GET"}
    assert [e["kind"] for e in f.log] == ["robots", "homepage", "sitemap"]
    assert all(e["ua"].startswith("AivexiaScanBot") for e in f.log)
    assert all(r.headers["user-agent"].startswith("AivexiaScanBot") for r in web.requests)


@pytest.mark.anyio
async def test_sitemap_index_prefers_stock_child():
    idx = (
        "<sitemapindex><sitemap><loc>https://a.example/blog.xml</loc></sitemap>"
        "<sitemap><loc>https://a.example/vehicles.xml</loc></sitemap></sitemapindex>"
    )
    web = FakeWeb({
        "a.example/": HOME,
        "a.example/sitemap.xml": (200, XML, idx),
        "a.example/vehicles.xml": (200, XML, "<urlset><loc>https://a.example/stoc/9</loc></urlset>"),
    })
    f = fetcher(web)
    acq = await acquire_homepage(f, normalize_input("a.example"))
    assert await load_sitemap_urls(f, acq) == ["https://a.example/stoc/9"]


@pytest.mark.anyio
async def test_sitemap_failure_is_not_fatal():
    web = FakeWeb({"a.example/": HOME})
    f = fetcher(web)
    acq = await acquire_homepage(f, normalize_input("a.example"))
    assert await load_sitemap_urls(f, acq) == []


@pytest.mark.anyio
async def test_robots_disallow_blocks_homepage():
    web = FakeWeb({
        "a.example/robots.txt": (200, TXT, "User-agent: AivexiaScanBot\nDisallow: /"),
        "a.example/": HOME,
    })
    with pytest.raises(ScanError) as e:
        await acquire_homepage(fetcher(web), normalize_input("a.example"))
    assert e.value.code == "BLOCKED_BY_ROBOTS"
    assert all(r.url.path == "/robots.txt" for r in web.requests)


@pytest.mark.anyio
async def test_robots_5xx_means_disallow():
    web = FakeWeb({"a.example/robots.txt": (503, {}, "down"), "a.example/": HOME})
    with pytest.raises(ScanError) as e:
        await acquire_homepage(fetcher(web), normalize_input("a.example"))
    assert e.value.code == "BLOCKED_BY_ROBOTS"


@pytest.mark.anyio
async def test_robots_404_allows():
    web = FakeWeb({"a.example/": HOME})
    acq = await acquire_homepage(fetcher(web), normalize_input("a.example"))
    assert acq.homepage.status == 200


@pytest.mark.anyio
@pytest.mark.parametrize("status", [403, 429, 503])
async def test_waf_block_status(status):
    web = FakeWeb({"a.example/": html_page("blocked", status)})
    with pytest.raises(ScanError) as e:
        await acquire_homepage(fetcher(web), normalize_input("a.example"))
    assert e.value.code == "BLOCKED_BY_WAF"


@pytest.mark.anyio
async def test_not_html():
    web = FakeWeb({"a.example/": (200, {"content-type": "application/pdf"}, "%PDF")})
    with pytest.raises(ScanError) as e:
        await acquire_homepage(fetcher(web), normalize_input("a.example"))
    assert e.value.code == "NOT_HTML"


@pytest.mark.anyio
async def test_follows_redirect_to_www_and_reports_canonical_origin():
    web = FakeWeb({
        "a.example/": (301, {"location": "https://www.a.example/"}, ""),
        "www.a.example/": HOME,
    })
    acq = await acquire_homepage(fetcher(web), normalize_input("a.example"))
    assert acq.origin == "https://www.a.example"
    assert acq.homepage.redirects == ["https://a.example/"]


@pytest.mark.anyio
async def test_www_fallback_when_apex_does_not_resolve():
    async def resolver(host):
        if host == "a.example":
            raise ScanError("DNS_FAIL", "nope")
        return ["93.184.216.34"]

    web = FakeWeb({"www.a.example/": HOME})
    acq = await acquire_homepage(fetcher(web, resolver), normalize_input("a.example"))
    assert acq.origin == "https://www.a.example"


@pytest.mark.anyio
async def test_https_failure_falls_back_to_http():
    def handler(req: httpx.Request):
        if req.url.scheme == "https":
            raise httpx.ConnectError("tls")
        return HOME

    f = SafeFetcher(transport=httpx.MockTransport(handler), resolver=public_resolver)
    acq = await acquire_homepage(f, normalize_input("a.example"))
    assert acq.origin == "http://a.example"


@pytest.mark.anyio
async def test_unreachable():
    def handler(req):
        raise httpx.ConnectError("down")

    f = SafeFetcher(transport=httpx.MockTransport(handler), resolver=public_resolver)
    with pytest.raises(ScanError) as e:
        await acquire_homepage(f, normalize_input("a.example"))
    assert e.value.code == "UNREACHABLE"


@pytest.mark.anyio
async def test_redirect_to_private_ip_is_blocked_and_never_requested():
    web = FakeWeb({"a.example/": (302, {"location": "http://169.254.169.254/latest/meta-data"}, "")})
    with pytest.raises(ScanError) as e:
        await acquire_homepage(fetcher(web), normalize_input("a.example"))
    assert e.value.code == "BLOCKED_TARGET"
    assert all(r.url.host != "169.254.169.254" for r in web.requests)


@pytest.mark.anyio
async def test_redirect_to_hostname_resolving_private_is_blocked():
    async def resolver(host):
        return ["10.0.0.7"] if host == "internal.evil.example" else ["93.184.216.34"]

    web = FakeWeb({
        "a.example/": (302, {"location": "https://internal.evil.example/"}, ""),
        "internal.evil.example/": HOME,
    })
    with pytest.raises(ScanError) as e:
        await acquire_homepage(fetcher(web, resolver), normalize_input("a.example"))
    assert e.value.code == "BLOCKED_TARGET"
    assert all(r.url.host != "internal.evil.example" for r in web.requests)


@pytest.mark.anyio
async def test_redirect_loop_gives_up():
    web = FakeWeb({"a.example/": (302, {"location": "https://a.example/"}, "")})
    with pytest.raises(ScanError) as e:
        await acquire_homepage(fetcher(web), normalize_input("a.example"))
    assert e.value.code == "UNREACHABLE"


@pytest.mark.anyio
async def test_body_is_capped():
    web = FakeWeb({"a.example/": html_page("x" * 3_000_000)})
    res = await fetcher(web).fetch("https://a.example/", kind="homepage")
    assert len(res.text) == 2_000_000
