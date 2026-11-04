from __future__ import annotations

from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent
CLASSIFY = Path(__file__).resolve().parent / "fixtures" / "classify"
PUBLIC_IP = "93.184.216.34"


def read_fixture(name: str) -> str:
    for base in (CLASSIFY, ROOT / "fixtures"):
        p = base / name
        if p.exists():
            return p.read_text(encoding="utf-8")
    raise FileNotFoundError(name)


async def public_resolver(host: str) -> list[str]:
    return [PUBLIC_IP]


class FakeWeb:
    """httpx.MockTransport backed by a {(host, path): response} table. Records every request."""

    def __init__(self, routes: dict[str, httpx.Response | tuple]) -> None:
        self.routes = routes
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        key = f"{request.url.host}{request.url.path}"
        r = self.routes.get(key)
        if r is None:
            return httpx.Response(404, text="not found")
        if isinstance(r, tuple):
            status, headers, body = r
            return httpx.Response(status, headers=headers, text=body)
        return r

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)


def html_page(body: str, status: int = 200) -> httpx.Response:
    return httpx.Response(status, headers={"content-type": "text/html; charset=utf-8"}, text=body)


@pytest.fixture
def web_factory():
    return FakeWeb


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def _no_politeness_delay(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "journey_delay_s", 0.0)
    for name in ("fetch_retry_delay_s", "probe_delay_s", "probe_retry_delay_s", "llm_retry_delay_s"):
        monkeypatch.setattr(settings, name, 0.0)
