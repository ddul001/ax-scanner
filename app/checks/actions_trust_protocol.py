"""Actions, Trust, Protocol layers for dealers (act.*, trust.*, proto.*). Read-only: forms are inspected, never submitted."""
from __future__ import annotations

import json
import re
from typing import Any

from app.checks.context import Page, ScanContext
from app.checks.util import CAPTCHA_MARKERS, res
from app.domain.scoring import CheckResult
from app.services.signals import fold

_TEST_DRIVE = re.compile(r"test[ -]?drive|prueba de conduccion|proba la drum")
PERSONAL = {
    "name", "first_name", "last_name", "fname", "lname", "nume", "prenume", "email", "mail",
    "phone", "tel", "telefon", "telephone", "nombre", "apellido", "telefono",
}
AUTOCOMPLETE_FIELDS = {"given-name", "family-name", "name", "email", "tel", "street-address", "postal-code"}


def _td_links(page: Page) -> list[str]:
    return [u for u, t in page.links if _TEST_DRIVE.search(fold(t)) or _TEST_DRIVE.search(u.lower())]


def _has_captcha(html: str) -> bool:
    low = html.lower()
    return any(m in low for m in CAPTCHA_MARKERS)


async def test_drive(ctx: ScanContext, spec: dict[str, Any]) -> CheckResult:
    vdps = ctx.ok_by_role("vdp")
    from_vdp = [(p.url, link) for p in vdps for link in _td_links(p)]
    pages_td = ctx.ok_by_role("test_drive")
    from_other = [(p.url, link) for p in ctx.ok_by_role("home", "stock_list", "service") for link in _td_links(p)]
    forms_on_vdp = [p.url for p in vdps if _TEST_DRIVE.search(fold(p.text)) and p.tree.css("form")]
    if not (from_vdp or pages_td or from_other or forms_on_vdp):
        return res(spec, "fail", "No test-drive booking found on the homepage, stock pages or vehicle pages.",
                   missing=["test-drive entry point"])
    captcha = [p.url for p in pages_td if _has_captcha(p.html)]
    reach = "vehicle pages" if (from_vdp or forms_on_vdp) else "other pages (not from a vehicle page)"
    if (from_vdp or forms_on_vdp) and not captcha:
        return res(spec, "pass", "Test-drive booking is reachable from vehicle pages and shows no CAPTCHA.",
                   pages=[u for u, _ in from_vdp][:2] + forms_on_vdp[:1], found=["link/form on VDP"])
    why = "a CAPTCHA protects the form" if captcha else f"it is only reachable from {reach}"
    return res(spec, "warn", f"Test-drive booking exists but {why}.", pages=[p.url for p in pages_td][:2],
               found=["test-drive page" if pages_td else "link"], missing=["VDP entry point" if not from_vdp else "no CAPTCHA"])


def _input_label(page: Page, field: Any) -> bool:
    attrs = field.attributes
    if attrs.get("aria-label") or attrs.get("aria-labelledby"):
        return True
    field_id = attrs.get("id")
    if field_id and page.tree.css_first(f'label[for="{field_id}"]'):
        return True
    parent = field.parent
    while parent is not None and parent.tag not in ("form", "body", "html"):
        if parent.tag == "label":
            return True
        parent = parent.parent
    return False


async def forms_semantic(ctx: ScanContext, spec: dict[str, Any]) -> CheckResult:
    inputs = []
    pages = []
    for page in ctx.ok_by_role("test_drive", "contact", "vdp"):
        forms = page.tree.css("form")
        if not forms:
            continue
        pages.append(page.url)
        for form in forms:
            for field in form.css("input, select, textarea"):
                input_type = (field.attributes.get("type") or "text").lower()
                if field.tag == "input" and input_type in ("hidden", "submit", "button", "checkbox", "radio", "image", "search"):
                    continue
                inputs.append((page, field))
    if not inputs:
        return res(spec, "na", "No lead/contact form found on the crawled pages.")
    labelled = [f for p, f in inputs if _input_label(p, f) and f.attributes.get("name")]
    personal = [
        f for _, f in inputs
        if fold(f.attributes.get("name") or "") in PERSONAL or (f.attributes.get("type") or "") in ("email", "tel")
    ]
    with_ac = [f for f in personal if (f.attributes.get("autocomplete") or "").split(" ")[-1] in AUTOCOMPLETE_FIELDS]
    label_share = len(labelled) / len(inputs)
    ac_share = len(with_ac) / len(personal) if personal else 1.0
    status = "pass" if label_share >= 0.8 and ac_share >= 0.8 else "warn" if min(label_share, ac_share) >= 0.5 else "fail"
    missing = []
    if label_share < 0.8:
        missing.append("label + name on every field")
    if ac_share < 0.8:
        missing.append("autocomplete on personal fields")
    return res(spec, status, f"{len(labelled)}/{len(inputs)} fields have label and name; autocomplete on "
                             f"{len(with_ac)}/{len(personal)} personal fields.",
               pages=pages, missing=missing,
               details={"label_name_share": round(label_share, 2), "autocomplete_share": round(ac_share, 2)})


async def https(ctx: ScanContext, spec: dict[str, Any]) -> CheckResult:
    if not ctx.origin.startswith("https://"):
        return res(spec, "fail", "The site is served over plain HTTP.", missing=["HTTPS"])
    result = await ctx.http_redirect()
    if not result.get("tested"):
        return res(spec, "warn", "HTTPS with a valid certificate; HTTP->HTTPS redirect could not be tested.")
    if result.get("https") or result.get("error"):
        return res(spec, "pass", "HTTPS with a valid certificate and http:// redirects to https:// (or is closed).",
                   details=result)
    return res(spec, "warn", "HTTPS works, but plain http:// is served without redirecting to https://.",
               missing=["HTTP->HTTPS redirect"], details=result)


async def aap_card(ctx: ScanContext, spec: dict[str, Any]) -> CheckResult:
    result = await ctx.fetch_text("/.well-known/agent-card.json", "agent-card")
    if result is None or result.status != 200:
        return res(spec, "fail", "No AAP agent card (/.well-known/agent-card.json): protocol not adopted yet.",
                   missing=["agent-card.json"], not_adopted=True,
                   details={"opportunity": "Publish an Auto Agent Protocol v3.0 agent card + llms.txt to be usable by agents."})
    try:
        card = json.loads(result.text)
    except ValueError:
        return res(spec, "warn", "agent-card.json exists but is not valid JSON.", missing=["valid JSON"])
    blob = json.dumps(card)
    version = re.search(r"autoagentprotocol\.org/extensions/aap/v?([\d.]+)", blob)
    if version:
        return res(spec, "pass", f"AAP agent card present, extension v{version.group(1)} declared.",
                   found=["agent-card.json", "AAP extension"], details={"aap_version": version.group(1)})
    return res(spec, "warn", "An agent card exists but declares no AAP extension.", found=["agent-card.json"],
               missing=["AAP extension"])
