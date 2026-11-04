"""Agent Journey for brand sites (ux.j_dealer): the agent looks for the nearest dealer and its answer is checked on the page."""
import pytest

from app.checks.context import build_context
from app.checks.engine import load_template, run_checks
from app.journey.agent import AgentStep
from app.journey.tasks import importer_task, market_city
from app.services.crawler import acquire_homepage
from app.services.url_normalizer import normalize_input
from tests.test_checks_importer import HOST, build_brand
from tests.test_journey import FakeLlm, finish, link


async def run(policy):
    web, factory = build_brand()
    fetcher = factory()
    acq = await acquire_homepage(fetcher, normalize_input(HOST))
    ctx = await build_context(acq, HOST, "importer", fetcher, factory, delay_s=0)
    ctx.llm = FakeLlm(policy)
    results = {r.check_id: r for r in await run_checks(ctx, load_template("importer"))}
    await fetcher.aclose()
    return results, ctx.llm


def good(page, step, _):
    if step == 1:
        return AgentStep(thought="dealer network", action="open_link", link_index=link(page, "/dealeri/"))
    return finish(found=True, url=page["url"], dealer_name="Dealer Velora Oras0", address="Str. Exemplu nr. 0", phone="0264 000 100")


@pytest.mark.anyio
async def test_dealer_journey_passes_and_is_recorded():
    res, llm = await run(good)
    r = res["ux.j_dealer"]
    assert r.status == "pass", r.summary
    j = r.details["journey"]
    assert [s["action"] for s in j["steps"]] == ["start", "open_link", "finish"] and j["path"][-1].endswith("/dealeri/")
    assert "nearest authorized dealer" in j["goal"] and "capital city" in j["goal"]  # b.example has no market city
    assert r.details["verification"]["checks"]["phone_or_email_on_page"] is True
    # the agent saw locator links first on a brand site
    assert llm.calls[0]["current_page"]["links"][0]["url"].endswith(("/modele/", "/dealeri/", "/test-drive/", "/contact/", "/oferte/", "/configurator/"))


@pytest.mark.anyio
async def test_invented_dealer_details_fail_verification():
    def liar(page, step, _):
        if step == 1:
            return AgentStep(thought="dealer network", action="open_link", link_index=link(page, "/dealeri/"))
        return finish(found=True, url=page["url"], dealer_name="Autohaus Phantasie", address="Nirgendwo 1", phone="0999 888 777")

    r = (await run(liar))[0]["ux.j_dealer"]
    assert r.status == "fail" and r.details["verification"]["checks"]["name_on_page"] is False


@pytest.mark.anyio
async def test_agent_that_finds_nothing_fails_and_a_partial_answer_warns():
    r = (await run(lambda p, s, u: finish(found=False, notes="no dealer list in the HTML")))[0]["ux.j_dealer"]
    assert r.status == "fail"

    def partial(page, step, _):
        if step == 1:
            return AgentStep(thought="network", action="open_link", link_index=link(page, "/dealeri/"))
        return finish(found=True, url=page["url"], dealer_name="Dealer Velora Oras0", address="Somewhere else entirely", phone="0264 000 100")

    assert (await run(partial))[0]["ux.j_dealer"].status == "warn"


def test_task_is_concrete_per_market():
    assert market_city("www.dacia.ro") == "Bucharest" and market_city("volkswagen.at") == "Vienna" and market_city("x.com") is None
    t = importer_task("renault.fr", "Clio")
    assert "in Paris" in t and "sells the Clio" in t and "Do NOT submit" in t


def test_discovered_links_come_first_and_locator_pages_show_more():
    from app.checks.context import Page
    from app.journey.browser import LOCATOR_LINKS, MAX_LINKS, build_view

    menu = "".join(f"<a href='/x{i}'>x{i}</a>" for i in range(80))
    page = Page("https://b.example/", "journey", 200, f"<html><body>{menu}<a href='/trouver-un-etablissement'>Trouver</a></body></html>")
    plain = build_view(page, "importer")
    assert len(plain.links) == MAX_LINKS and not any("etablissement" in link.url for link in plain.links)
    hinted = build_view(page, "importer", frozenset({"b.example/trouver-un-etablissement"}))
    assert hinted.links[0].url.endswith("/trouver-un-etablissement")  # the discovery step's pick leads the list

    rows = "".join(f"<a href='/dealeri/oras-{i}'>Dealer {i}</a>" for i in range(200))
    loc = Page("https://b.example/dealeri/", "journey", 200, f"<html><body>{rows}</body></html>")
    assert len(build_view(loc, "importer").links) == LOCATOR_LINKS > MAX_LINKS
    assert len(build_view(loc, "dealer").links) == MAX_LINKS  # dealer sites keep the old limit
