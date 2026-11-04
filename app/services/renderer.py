"""Playwright fallback for JS-only homepages. Imported lazily; failures are non-fatal."""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from app.config import settings
from app.services.url_normalizer import ScanError, resolve_public

if TYPE_CHECKING:
    from playwright.async_api import Route

log = logging.getLogger(__name__)
Renderer = Callable[[str], Awaitable[str | None]]


async def render_html(url: str) -> str | None:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return None
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            try:
                ctx = await browser.new_context(user_agent=settings.bot_user_agent)
                checked: dict[str, bool] = {}

                async def guard(route: Route) -> None:
                    if route.request.method != "GET":  # read-only: never send side-effect requests
                        return await route.abort()
                    host = urlsplit(route.request.url).hostname or ""
                    if route.request.url.startswith(("data:", "blob:")):
                        return await route.continue_()
                    if host not in checked:
                        try:
                            await resolve_public(host)
                            checked[host] = True
                        except ScanError:
                            checked[host] = False
                    await (route.continue_() if checked[host] else route.abort())

                await ctx.route("**/*", guard)
                page = await ctx.new_page()
                await page.goto(url, wait_until="networkidle", timeout=15_000)
                return await page.content()
            finally:
                await browser.close()
    except Exception as e:  # noqa: BLE001 - rendering is best effort
        log.warning("playwright render failed: %s", e)
        return None
