"""Input normalization + SSRF guard for user-supplied domains."""
from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urlsplit


class ScanError(Exception):
    """Typed, user-facing failure. `code` is stable and shown in the API/UI."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(f"{code}: {message}" if message else code)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Target:
    host: str
    origin: str  # https://host


Resolver = Callable[[str], Awaitable[list[str]]]

_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
_TLD = re.compile(r"^(?:[a-z]{2,63}|xn--[a-z0-9-]{2,59})$")
_BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home", ".corp")


def normalize_input(raw: str) -> Target:
    value = (raw or "").strip()
    if not value or len(value) > 2048 or re.search(r"\s", value):
        raise ScanError("INVALID_URL", "Enter a domain like example.com")
    if "://" not in value:
        value = "https://" + value.lstrip("/")
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        raise ScanError("INVALID_URL", "Malformed URL") from None
    if parts.scheme not in ("http", "https"):
        raise ScanError("INVALID_URL", "Only http/https URLs are supported")
    if parts.username or parts.password:
        raise ScanError("INVALID_URL", "Credentials in URL are not allowed")
    if port not in (None, 80, 443):
        raise ScanError("INVALID_URL", "Non-standard ports are not allowed")
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        raise ScanError("INVALID_URL", "Missing host")
    host = _validate_host(host)
    return Target(host=host, origin=f"https://{host}")


def _validate_host(host: str) -> str:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ScanError("INVALID_URL", "IP addresses are not allowed")
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError:
        raise ScanError("INVALID_URL", "Invalid domain name") from None
    if host == "localhost" or host.endswith(_BLOCKED_SUFFIXES) or len(host) > 253:
        raise ScanError("INVALID_URL", "Not a public domain")
    labels = host.split(".")
    if len(labels) < 2 or not _TLD.match(labels[-1]) or not all(_LABEL.match(x) for x in labels):
        raise ScanError("INVALID_URL", "Enter a domain like example.com")
    return host


def validate_url(url: str) -> str:
    """Validate an absolute URL (e.g. a redirect Location); returns its host."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise ScanError("INVALID_URL", "Malformed redirect") from None
    if parts.scheme not in ("http", "https") or parts.username or parts.password:
        raise ScanError("INVALID_URL", "Unsupported URL")
    if port not in (None, 80, 443):
        raise ScanError("BLOCKED_TARGET", "Non-standard port")
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        raise ScanError("INVALID_URL", "Missing host")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return _validate_host(host)
    check_ip(str(ip))
    return host


def check_ip(ip_str: str) -> None:
    ip = ipaddress.ip_address(ip_str.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    if not ip.is_global or ip.is_multicast:
        raise ScanError("BLOCKED_TARGET", "Target resolves to a non-public address")


async def system_resolver(host: str) -> list[str]:
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise ScanError("DNS_FAIL", f"Could not resolve {host}") from None
    return sorted({i[4][0] for i in infos})


async def resolve_public(host: str, resolver: Resolver | None = None) -> list[str]:
    """Resolve `host` and ensure every address is public. Raises ScanError otherwise."""
    try:
        ipaddress.ip_address(host)
        ips = [host]
    except ValueError:
        ips = await (resolver or system_resolver)(host)
    if not ips:
        raise ScanError("DNS_FAIL", f"Could not resolve {host}")
    for ip in ips:
        check_ip(ip)
    return ips
