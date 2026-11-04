import pytest

from app.services.url_normalizer import ScanError, check_ip, normalize_input, resolve_public, validate_url


@pytest.mark.parametrize(
    "raw,host",
    [
        ("example.com", "example.com"),
        ("  Example.COM  ", "example.com"),
        ("https://www.example.ro/stoc?x=1#a", "www.example.ro"),
        ("http://example.es:80/", "example.es"),
        ("https://example.es:443", "example.es"),
        ("example.com.", "example.com"),
        ("//example.com/path", "example.com"),
        ("bücher.de", "xn--bcher-kva.de"),
        ("sub.domain.example.co.uk", "sub.domain.example.co.uk"),
        ("xn--bcher-kva.de", "xn--bcher-kva.de"),
    ],
)
def test_valid_inputs(raw, host):
    t = normalize_input(raw)
    assert t.host == host and t.origin == f"https://{host}"


@pytest.mark.parametrize(
    "raw",
    [
        "", "   ", "localhost", "http://localhost:8000", "127.0.0.1", "http://10.0.0.1/", "[::1]",
        "example", "ftp://example.com", "javascript:alert(1)", "file:///etc/passwd",
        "https://user:pw@example.com", "example.com:8080", "exa mple.com", "foo.local",
        "service.internal", "-bad-.com", "a..b.com", "example.123", "127.1", "2130706433",
        "x" * 3000,
    ],
)
def test_invalid_inputs(raw):
    with pytest.raises(ScanError) as e:
        normalize_input(raw)
    assert e.value.code == "INVALID_URL"


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1", "10.1.2.3", "172.16.0.1", "192.168.1.1", "169.254.169.254", "0.0.0.0",
        "100.64.0.1", "::1", "fc00::1", "fe80::1", "::ffff:127.0.0.1", "::ffff:10.0.0.1", "224.0.0.1",
    ],
)
def test_private_ips_blocked(ip):
    with pytest.raises(ScanError) as e:
        check_ip(ip)
    assert e.value.code == "BLOCKED_TARGET"


def test_public_ip_ok():
    check_ip("93.184.216.34")
    check_ip("2606:2800:220:1:248:1893:25c8:1946")


@pytest.mark.anyio
async def test_resolve_blocks_if_any_address_private():
    async def mixed(_):
        return ["93.184.216.34", "10.0.0.5"]

    with pytest.raises(ScanError) as e:
        await resolve_public("example.com", mixed)
    assert e.value.code == "BLOCKED_TARGET"


@pytest.mark.anyio
async def test_resolve_empty_is_dns_fail():
    async def none(_):
        return []

    with pytest.raises(ScanError) as e:
        await resolve_public("example.com", none)
    assert e.value.code == "DNS_FAIL"


def test_validate_url_redirect_targets():
    assert validate_url("https://example.com/x") == "example.com"
    for bad in ("http://169.254.169.254/latest", "http://[::1]/", "https://example.com:8443/", "gopher://example.com"):
        with pytest.raises(ScanError):
            validate_url(bad)
