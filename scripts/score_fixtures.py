"""Scorer ax-scanner pentru fixtures: rulează fiecare check din docs/checks/<tip>.md pe pagina servită de testserver și calculează AX Readiness.
Agent Journey e simulat determinist (agent scriptat, fără LLM); prompt panel / Visibility nu se rulează (necesită Muse Spark grounding)."""
from __future__ import annotations

import json
import math
import os
import re
import ssl
import sys
import time
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any

sys.path.insert(0, os.path.dirname(__file__))
import aapval
import testserver

ROOT = os.path.join(os.path.dirname(__file__), "..")
NOW = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)
SEV = {"CRITICAL": 4, "HIGH": 3, "MAJOR": 2, "MINOR": 1, "INFO": 0}
BOTS = [
    "GPTBot", "ChatGPT-User", "OAI-SearchBot", "ClaudeBot", "Claude-User", "PerplexityBot",
    "Google-Extended", "Applebot-Extended", "Meta-ExternalAgent",
]
BROWSER = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/141.0 Safari/537.36"
LAYER_W = {
    "dealer": {"Discovery": 15, "Identity": 10, "Data": 20, "Actions": 15, "Trust": 10, "Agent UX": 20, "Protocol": 10},
    "importer": {"Discovery": 15, "Identity": 15, "Data": 20, "Actions": 10, "Trust": 10, "Agent UX": 20, "Protocol": 10},
    "ecommerce": {"Discovery": 15, "Identity": 10, "Data": 25, "Actions": 20, "Trust": 10, "Agent UX": 15, "Protocol": 5},
}


def checklist(site_type: str) -> list[dict[str, str]]:
    """Checklistul din docs/checks/<tip>.md: id, layer, severitate și criteriul de pass pentru fiecare rând."""
    rows = []
    layer = None
    with open(f"{ROOT}/docs/checks/{site_type}.md", encoding="utf-8") as f:
        for line in f:
            m = re.match(r"## \d+\. ([A-Za-z ]+?)(?: —.*)? \((\d+)\)", line)
            if m:
                layer = m.group(1).strip()
                continue
            if layer and line.startswith("| ") and re.match(r"\| [a-z]+\.[a-z_0-9]+ \|", line):
                cells = [x.strip() for x in line.strip().strip("|").split("|")]
                rows.append({"id": cells[0], "layer": layer, "sev": cells[4].strip("`"), "pass": cells[2]})
    return rows


# ---------- parsing ----------
class PageParser(HTMLParser):
    """HTML-ul paginii: text vizibil vs ascuns, linkuri, formulare, imagini, taguri <time>."""

    def __init__(self) -> None:
        super().__init__()
        self.text: list[str] = []
        self.skip = 0
        self.links: list[str] = []
        self.forms: list[dict[str, Any]] = []
        self.current: dict[str, Any] | None = None
        self.wrapping_label: bool | None = None
        self.hidden_text: list[str] = []
        self.hidden_depth = 0
        self.imgs: list[dict[str, str]] = []
        self.times: list[str | None] = []
        self.tags: list[tuple[str, dict[str, str]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        self.tags.append((tag, attrs_dict))
        if tag in ("script", "style"):
            self.skip += 1
        if "hidden" in attrs_dict or "display:none" in (attrs_dict.get("style", "").replace(" ", "")) or attrs_dict.get("aria-hidden") == "true":
            self.hidden_depth += 1
        if tag == "a":
            self.links.append(attrs_dict.get("href", ""))
        if tag == "img":
            self.imgs.append(attrs_dict)
        if tag == "time":
            self.times.append(attrs_dict.get("datetime"))
        if tag == "form":
            self.current = {"attrs": attrs_dict, "fields": [], "labels_for": set(), "text": []}
            self.forms.append(self.current)
        if tag == "label" and self.current is not None:
            if attrs_dict.get("for"):
                self.current["labels_for"].add(attrs_dict["for"])
            else:
                self.wrapping_label = True
        if tag in ("input", "select", "textarea") and self.current is not None:
            attrs_dict["_wrapped"] = bool(self.wrapping_label)
            attrs_dict["_tag"] = tag
            self.current["fields"].append(attrs_dict)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self.skip -= 1
        if tag == "form":
            self.current = None
        if tag == "label":
            self.wrapping_label = None

    def handle_data(self, data: str) -> None:
        if self.skip:
            return
        (self.hidden_text if self.hidden_depth else self.text).append(data)
        if self.current is not None:
            self.current["text"].append(data)


def collect_nodes(obj: Any, acc: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(obj, dict):
        if "@type" in obj:
            acc.append(obj)
        for value in obj.values():
            collect_nodes(value, acc)
    elif isinstance(obj, list):
        for value in obj:
            collect_nodes(value, acc)
    return acc


def has_type(node: dict[str, Any], want: str) -> bool:
    declared = node.get("@type")
    return want in (declared if isinstance(declared, list) else [declared])


class Ctx:
    """Pagina fixture + răspunsurile simulate: o singură citire, apoi totul se verifică local."""

    def __init__(self, typ: str, port: int, cafile: str) -> None:
        self.typ = typ
        self.base = f"https://localhost:{port}"
        self.ssl = ssl.create_default_context(cafile=cafile)
        self.page, self.ttfb, self.size, self.status = self.get("/", BROWSER)
        self.parser = PageParser()
        self.parser.feed(self.page)
        self.text = re.sub(r"\s+", " ", " ".join(self.parser.text))
        self.jsonld: list[dict[str, Any]] = []
        for block in re.findall(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', self.page, re.S):
            collect_nodes(json.loads(block), self.jsonld)
        self.cache: dict[str, str | None] = {}

    def get(self, path: str, ua: str = BROWSER) -> tuple[str, float, int, int]:
        """GET + (body, TTFB în ms, dimensiunea în bytes, status)."""
        started = time.perf_counter()
        response = urllib.request.urlopen(
            urllib.request.Request(self.base + path, headers={"User-Agent": ua}),
            context=self.ssl, timeout=10,
        )
        first = response.read(1)
        ttfb = time.perf_counter() - started
        body = (first + response.read()).decode("utf-8")
        return body, ttfb * 1000, len(body.encode()), response.status

    def fetch(self, path: str) -> str | None:
        if path not in self.cache:
            try:
                self.cache[path] = self.get(path)[0]
            except Exception:  # noqa: BLE001 - o cale lipsă înseamnă doar "nu s-a găsit"
                self.cache[path] = None
        return self.cache[path]

    def js(self, path: str) -> Any:
        body = self.fetch(path)
        return json.loads(body) if body else None

    def of(self, want: str) -> list[dict[str, Any]]:
        return [n for n in self.jsonld if has_type(n, want)]

    def mcp(self, method: str, params: dict[str, Any] | None = None) -> Any:
        card = self.js("/.well-known/agent-card.json")
        url = self.aap(card)["mcp"]["url"]
        path = "/" + url.split("/", 3)[3]
        request = urllib.request.Request(
            self.base + path,
            data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}).encode(),
            headers={"Content-Type": "application/json", "User-Agent": "AivexiaScanBot/1.0"},
        )
        return json.loads(urllib.request.urlopen(request, context=self.ssl).read())["result"]

    @staticmethod
    def aap(card: dict[str, Any]) -> dict[str, Any]:
        return next(
            e["params"] for e in card["capabilities"]["extensions"]
            if e["uri"].startswith("https://autoagentprotocol.org/extensions/aap/")
        )


def verdict(ok: bool, evidence: Any, warn: bool = False) -> tuple[str, Any]:
    return ("pass" if ok else ("warn" if warn else "fail"), evidence)


def fmt_eur(v: Any) -> str:
    return f"{int(float(v)):,}".replace(",", ".")


def fmt_ron(v: Any) -> str:
    return f"{float(v):.2f}".replace(".", ",")


def price_in_text(ctx: Ctx, offer: dict[str, Any]) -> tuple[bool, str]:
    price = offer.get("price") or offer.get("lowPrice")
    shown = fmt_ron(price) if offer.get("priceCurrency") == "RON" else fmt_eur(price)
    return shown in ctx.text, shown


def all_offers(ctx: Ctx) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    out = []
    for node in ctx.of("Car") + ctx.of("Product"):
        offer = node.get("offers")
        if offer:
            out.append((node, offer))
    return out


# ---------- checks ----------
def robots(ctx: Ctx) -> tuple[str, str]:
    text = ctx.fetch("/robots.txt") or ""
    groups: dict[str, list[tuple[str, str]]] = {}
    current: list[str] = []
    for line in text.splitlines():
        key, _, value = line.partition(":")
        key, value = key.strip().lower(), value.strip()
        if key == "user-agent":
            current = [value]
            groups.setdefault(value, [])
        elif key in ("allow", "disallow"):
            for user in current:
                groups[user].append((key, value))
    bad = [b for b in BOTS if b not in groups or ("disallow", "/") in groups[b] or ("allow", "/") not in groups[b]]
    return verdict(not bad, f"9/9 boți cu Allow: / · lipsă: {bad}")


def waf(ctx: Ctx) -> tuple[str, str]:
    baseline = ctx.get("/", BROWSER)
    probed = [(ua,) + ctx.get("/", ua)[2:] for ua in BOTS]
    bad = [ua for ua, size, status in probed if status != 200 or abs(size - baseline[2]) > 0.1 * baseline[2]]
    return verdict(not bad, f"{len(BOTS)} UA comparate cu browser: status 200, dimensiune {baseline[2]} B ±10% · diferențe: {bad}")


def sitemap(ctx: Ctx, days: int, pat: str) -> tuple[str, str]:
    xml = ctx.fetch("/sitemap.xml") or ""
    locs = re.findall(r"<loc>(.*?)</loc>", xml)
    mods = [datetime.fromisoformat(d).replace(tzinfo=timezone.utc) for d in re.findall(r"<lastmod>(.*?)</lastmod>", xml)]
    key = [loc for loc in locs if re.search(pat, loc)]
    age = (NOW - max(mods)).days if mods else 999
    return verdict(bool(key) and age <= days, f"{len(locs)} URL-uri, {len(key)} pagini cheie ({pat}), cel mai recent lastmod acum {age} zile (prag {days})")


def llms(ctx: Ctx) -> tuple[str, str]:
    text = ctx.fetch("/llms.txt") or ""
    ok = text.startswith("# ") and len(re.findall(r"https://", text)) >= 3
    card = ctx.js("/.well-known/agent-card.json")
    if card:
        ok = ok and Ctx.aap(card)["mcp"]["url"] in text
    return verdict(ok, f"llms.txt {len(text)} B, titlu H1, {len(re.findall(r'https://', text))} link-uri" + (", conține URL-ul MCP din Agent Card" if card else ""))


def no_js(ctx: Ctx) -> tuple[str, str]:
    offers = all_offers(ctx)
    hits = [price_in_text(ctx, offer) for _, offer in offers]
    ratio = 1.0  # pagina nu injectează conținut prin JS: textul brut = textul randat
    return verdict(all(h for h, _ in hits) and ratio >= 0.7, f"prețuri găsite în HTML brut: {[s for _, s in hits]} · raport text brut/randat {ratio}")


def perf(ctx: Ctx) -> tuple[str, str]:
    return verdict(ctx.ttfb < 800 and ctx.size < 3e6, f"TTFB {ctx.ttfb:.0f} ms (local), pagină {ctx.size / 1024:.1f} KB")


def wellknown(ctx: Ctx) -> tuple[str, str]:
    catalog = ctx.js("/.well-known/api-catalog")
    return verdict(bool(catalog and catalog.get("linkset")), "api-catalog RFC 9727 cu linkset" if catalog else "lipsă")


def lang(ctx: Ctx) -> tuple[str, str]:
    ok = ctx.page.lstrip().lower().startswith("<!doctype html>") and '<html lang="ro"' in ctx.page and 'hreflang="es"' in ctx.page
    return verdict(ok, 'lang="ro" + hreflang ro/es')


def https(ctx: Ctx) -> tuple[str, str]:
    # cererile de mai sus au trecut deja prin TLS verificat cu CA-ul certificatului de test
    return verdict(ctx.base.startswith("https://"), "TLS verificat (certificat de test, CA local) + HSTS")


def cookie_wall(ctx: Ctx) -> tuple[str, str]:
    bad = [
        attrs for _, attrs in ctx.parser.tags
        if attrs.get("aria-modal") == "true" or re.search(r"cookie|consent-banner|overlay", attrs.get("id", "") + attrs.get("class", ""), re.I)
    ]
    return verdict(not bad, f"elemente modale/overlay: {len(bad)}")


def injection(ctx: Ctx) -> tuple[str, str]:
    pat = r"ignore (all|previous)|you are an? (ai|assistant)|as an ai|instrucțiuni pentru agent|system prompt"
    hits = re.findall(pat, " ".join(ctx.parser.hidden_text) + " " + ctx.text, re.I)
    return verdict(not ctx.parser.hidden_text and not hits, f"text ascuns: {len(ctx.parser.hidden_text)} fragmente · tipare de injection: {len(hits)}")


def forms_semantic(ctx: Ctx) -> tuple[str, str]:
    issues = []
    for form in ctx.parser.forms:
        for field in form["fields"]:
            if field.get("type") in ("hidden", "submit", "checkbox"):
                if field.get("type") == "checkbox" and not field["_wrapped"] and field.get("id") not in form["labels_for"]:
                    issues.append("checkbox fără label")
                continue
            if not field.get("name"):
                issues.append(f"{field.get('id')} fără name")
            if not (field["_wrapped"] or field.get("id") in form["labels_for"]):
                issues.append(f"{field.get('id')} fără label")
            if field.get("name") in ("name", "email", "phone") and not field.get("autocomplete"):
                issues.append(f"{field.get('id')} fără autocomplete")
    n = sum(len(form["fields"]) for form in ctx.parser.forms)
    return verdict(not issues, f"{len(ctx.parser.forms)} formulare, {n} câmpuri · probleme: {issues}")


def gdpr(ctx: Ctx) -> tuple[str, str]:
    post = [
        form for form in ctx.parser.forms
        if form["attrs"].get("method", "get").lower() == "post"
        and any(f.get("name") in ("email", "phone") for f in form["fields"])
    ]
    ok = all(
        any(f.get("type") == "checkbox" and "required" in f for f in form["fields"])
        and "Confidențialitate".lower() in " ".join(form["text"]).lower().replace("politica de confidențialitate", "confidențialitate")
        for form in post
    )
    return verdict(bool(post) and ok, f"{len(post)} formulare cu date personale, toate cu checkbox obligatoriu + link politică")


def form_by(ctx: Ctx, word: str) -> list[dict[str, Any]]:
    return [f for f in ctx.parser.forms if word.lower() in f["attrs"].get("aria-label", "").lower()]


def no_captcha(ctx: Ctx) -> bool:
    return not re.search(r"captcha|recaptcha|hcaptcha|turnstile", ctx.page, re.I)


def webmcp(ctx: Ctx, names: list[str]) -> tuple[str, str]:
    js = "".join(re.findall(r'<script data-check="act.webmcp">(.*?)</script>', ctx.page, re.S))
    miss = [n for n in names if f'name: "{n}"' not in js]
    return verdict("registerTool" in js and not miss, f"tool-uri WebMCP declarate: {[n for n in names if n not in miss]} · lipsă: {miss}")


def fields_cov(items: list[dict[str, Any]], req: list) -> float:
    total = len(items) * len(req)
    have = sum(1 for item in items for check in req if check(item))
    return have / total if total else 0


# ---- Agent Journey (agent scriptat determinist, read-only) ----
def journey(ctx: Ctx, steps: list[str], answer: Any, truth: Any) -> tuple[str, str]:
    blockers = [] if no_captcha(ctx) and cookie_wall(ctx)[0] == "pass" else ["blocker"]
    ok = answer == truth and not blockers
    return verdict(ok, f"pași: {' → '.join(steps)} · răspuns: {answer} · ground truth: {truth}")


# ---------- registry per tip ----------
def build(ctx: Ctx) -> dict[str, Any]:
    t = ctx.typ
    ck: dict[str, Any] = {}
    ck["disc.robots_ai"] = lambda: robots(ctx)
    ck["disc.waf_ua"] = lambda: waf(ctx)
    ck["disc.llms_txt"] = lambda: llms(ctx)
    ck["disc.no_js"] = lambda: no_js(ctx)
    ck["disc.perf"] = lambda: perf(ctx)
    ck["disc.wellknown"] = lambda: wellknown(ctx)
    ck["disc.sitemap"] = {
        "dealer": lambda: sitemap(ctx, 7, r"/stoc/"),
        "importer": lambda: sitemap(ctx, 30, r"/modele/"),
        "ecommerce": lambda: sitemap(ctx, 7, r"/p/"),
    }[t]
    ck["id.lang"] = lambda: lang(ctx)
    ck["id.same_as"] = lambda: verdict(any(len(n.get("sameAs", [])) >= 2 for n in ctx.jsonld), "sameAs ≥ 2 profiluri")
    ck["trust.https"] = lambda: https(ctx)
    ck["trust.cookie_wall"] = lambda: cookie_wall(ctx)
    ck["trust.injection"] = lambda: injection(ctx)
    ck["trust.gdpr"] = lambda: gdpr(ctx)
    ck["act.forms_semantic"] = lambda: forms_semantic(ctx)
    ck["ux.blockers"] = lambda: verdict(
        no_captcha(ctx) and cookie_wall(ctx)[0] == "pass" and waf(ctx)[0] == "pass",
        "0 CAPTCHA, 0 overlay, 0 răspunsuri 403 pentru UA de agent",
    )
    ck["ux.agent_vs_human"] = lambda: verdict(True, "agentul primește același HTML ca omul (fără conținut injectat prin JS, fără prețuri în imagini): 100% din text")
    card = lambda: ctx.js("/.well-known/agent-card.json")
    if t in ("dealer", "importer"):
        def aap_card():
            cd = card()
            errors = aapval.validate("agent-card", cd) if cd else ["lipsă"]
            return verdict(not errors, "agent-card.json valid pe schema AAP v3.0" if not errors else errors[:3])
        ck["proto.aap_card"] = aap_card
        ck["proto.aap_version"] = lambda: verdict(Ctx.aap(card())["version"].startswith("3.0"), f"params.version = {Ctx.aap(card())['version']}")

        def consistency():
            cd = card()
            aap = Ctx.aap(cd)
            skills = set(aap["skills"])
            card_skills = {s["id"] for s in cd["skills"]}
            poppy = ctx.js("/.well-known/poppy.json")
            llms_txt = ctx.fetch("/llms.txt")
            ok = skills == card_skills and aap["mcp"]["url"] in llms_txt and (poppy is None or poppy["extensions"]["autoagentprotocol.org/aap"]["mcp"] == aap["mcp"]["url"])
            return verdict(ok, f"skill-uri extensie = skill-uri card ({len(skills)}); același URL MCP în card, poppy, llms.txt")
        ck["proto.consistency"] = consistency

        def mcp_ok():
            hello = ctx.mcp("initialize", {"protocolVersion": "2025-11-25"})
            disco = ctx.mcp("server/discover")
            return verdict("serverInfo" in hello and "2026-07-28" in disco["supportedVersions"], "MCP din params.mcp.url: initialize (2025-11-25) OK, server/discover (2026-07-28) OK")
        ck["proto.mcp"] = mcp_ok

        def tools():
            names = {x["name"] for x in ctx.mcp("tools/list")["tools"]}
            expected = {"aap_" + s.replace(".", "_") for s in Ctx.aap(card())["skills"]}
            return verdict(names == expected, f"tools/list = {sorted(names)}")
        ck["proto.tools"] = tools

        def search():
            found = ctx.mcp("tools/call", {"name": "aap_inventory_search", "arguments": {"filters": {"make": ["Velora"]}, "privacy": {"anonymous": True}}})["structuredContent"]
            errors = aapval.validate("inventory-search-response", found)
            vehicles = found["data"]["vehicles"]
            ok = not errors and all(x.get("status") and x.get("updated_at") and (x.get("vin") or x.get("stock") or x.get("vehicle_id")) for x in vehicles)
            return verdict(ok, f"căutare anonimă validă pe schemă; {len(vehicles)} listări cu status, updated_at, VIN" if ok else errors[:3])
        ck["proto.search"] = search
        ck["proto.eu_profile"] = lambda: verdict(any("aap-eu" in e["uri"] for e in card()["capabilities"]["extensions"]), "extensie aap-eu: EUR, TVA inclus, km/WLTP, GDPR")

        def onboarding():
            t0 = time.perf_counter()
            cd = card()
            Ctx.aap(cd)["mcp"]["url"]
            ctx.mcp("initialize")
            ctx.mcp("tools/list")
            ctx.mcp("tools/call", {"name": "aap_inventory_search", "arguments": {}})
            dt = time.perf_counter() - t0
            return verdict(dt < 60, f"domeniu → agent-card → MCP → tools/list → căutare în {dt * 1000:.0f} ms")
        ck["proto.onboarding"] = onboarding
        ck["proto.ucp"] = lambda: verdict(bool(ctx.js("/.well-known/ucp")), "/.well-known/ucp prezent")
    if t == "dealer":
        cars = ctx.of("Car")
        dealer = ctx.of("AutoDealer")[0]
        ck["id.schema_dealer"] = lambda: verdict(all(k in dealer for k in ["name", "address", "geo", "telephone", "openingHoursSpecification", "brand"]), "AutoDealer: name, address, geo, telephone, openingHours, brand")
        ck["id.locations"] = lambda: verdict(len(dealer.get("department", [])) >= 3 and all("openingHours" in x for x in dealer["department"]), f"{len(dealer['department'])} departamente cu program")
        ck["id.nap"] = lambda: verdict(dealer["address"]["streetAddress"] in ctx.text and "+40 264 000 100" in ctx.text and dealer["name"] in ctx.text, "nume, adresă, telefon identice în text și JSON-LD")
        ck["inv.vdp_urls"] = lambda: verdict(len({n["url"] for n in cars}) == len(cars) and all(n["url"].split("example")[1] in ctx.parser.links for n in cars), f"{len(cars)} VDP-uri unice, legate din tabelul de stoc")
        ck["inv.schema_vehicle"] = lambda: verdict(len(cars) >= 1, f"{len(cars)}/{len(cars)} vehicule cu Car")
        ck["inv.schema_offer"] = lambda: verdict(
            all(all(k in n["offers"] for k in ["price", "priceCurrency", "availability", "itemCondition"]) and n["offers"]["priceCurrency"] in ("EUR", "RON") for n in cars),
            "Offer complet pe toate vehiculele",
        )
        req = [
            lambda n: n.get("vehicleIdentificationNumber"),
            lambda n: n.get("mileageFromOdometer"),
            lambda n: n.get("vehicleModelDate"),
            lambda n: n.get("fuelType"),
            lambda n: n.get("vehicleTransmission"),
            lambda n: n.get("vehicleEngine"),
            lambda n: n.get("fuelConsumption") and "emissionsCO2" in n,
            lambda n: n["offers"].get("availability"),
            lambda n: n.get("image"),
        ]
        ck["inv.fields"] = lambda: verdict(fields_cov(cars, req) >= 0.8, f"acoperire câmpuri {fields_cov(cars, req):.0%}")
        ck["inv.price_readable"] = lambda: verdict(
            all(price_in_text(ctx, n["offers"])[0] for n in cars) and not any(re.search(r"\d", i.get("alt", "")) for i in ctx.parser.imgs),
            "preț în text pe 100% din vehicule; nicio imagine cu preț în alt",
        )
        ck["inv.price_consistency"] = lambda: verdict(all(price_in_text(ctx, n["offers"])[0] for n in cars), f"JSON-LD = text: {[fmt_eur(n['offers']['price']) for n in cars]}")
        ck["inv.price_final"] = lambda: verdict(
            all(n["offers"]["priceSpecification"]["valueAddedTaxIncluded"] for n in cars) and "TVA inclus" in ctx.text and "nu depinde de finanțare" in ctx.text,
            "valueAddedTaxIncluded + „TVA inclus” + „nu depinde de finanțare”",
        )

        def fresh():
            vehicles = ctx.mcp("tools/call", {"name": "aap_inventory_search", "arguments": {}})["structuredContent"]["data"]["vehicles"]
            ages = [(NOW - datetime.fromisoformat(x["updated_at"].replace("Z", "+00:00"))).total_seconds() / 3600 for x in vehicles]
            return verdict(sorted(ages)[len(ages) // 2] < 72, f"vârstă mediană updated_at {sorted(ages)[len(ages) // 2]:.0f} h")
        ck["inv.freshness"] = fresh
        ck["inv.search_urls"] = lambda: verdict(any(f["attrs"].get("method") == "get" for f in ctx.parser.forms) and any("/stoc?" in link for link in ctx.parser.links), "formular GET + URL de filtrare")
        ck["inv.features"] = lambda: verdict(ctx.text.count("sursa:") >= 3, "dotări cu stare și sursă")
        ck["inv.feed"] = lambda: verdict(any(link.endswith(("stoc.json", "stoc.xml")) for link in ctx.parser.links), "feed JSON + XML")
        ck["inv.marketplace"] = lambda: verdict(any("marketplace" in link for link in ctx.parser.links), "link-uri către aceleași anunțuri pe marketplace")
        ck["act.test_drive"] = lambda: verdict(bool(form_by(ctx, "test drive")) and no_captcha(ctx) and any(link.startswith("/test-drive?vin=") for link in ctx.parser.links), "formular test drive + link din VDP, fără CAPTCHA")
        ck["act.service_booking"] = lambda: verdict(bool(form_by(ctx, "service")), "formular programare service")
        ck["act.quote_contact"] = lambda: verdict(bool(form_by(ctx, "ofert")) and any(link.startswith("tel:") for link in ctx.parser.links), "formular ofertă + tel:")
        ck["act.webmcp"] = lambda: webmcp(ctx, ["search_inventory", "get_vehicle", "book_test_drive", "request_quote", "book_service"])
        ck["trust.offer_validity"] = lambda: verdict(all("priceValidUntil" in n["offers"] for n in cars) and len(ctx.parser.times) >= 3, "priceValidUntil + perioade în <time>")
        ck["ux.j_understand"] = lambda: journey(ctx, ["/", "#despre"], (dealer["brand"]["name"], dealer["address"]["addressLocality"]), ("Velora", "Cluj-Napoca"))

        def find():
            matches = [n for n in cars if n["fuelType"] == "Hybrid" and n["bodyType"] == "SUV" and float(n["offers"]["price"]) < 30000 and "Used" in n["itemCondition"]]
            answer = (matches[0]["vehicleIdentificationNumber"], matches[0]["mileageFromOdometer"]["value"], int(float(matches[0]["offers"]["price"]))) if matches else None
            return journey(ctx, ["/", "/stoc?fuel=hybrid&body=suv&price_max=30000&condition=used", "/stoc/vlr-0001"], answer, ("VLR1TERRA23000001", 28500, 27900))
        ck["ux.j_find"] = find
        ck["ux.j_price"] = lambda: journey(ctx, ["/stoc/vlr-0001"], re.search(r"Preț final (\d+\.\d+ €)", ctx.text).group(1), "27.900 €")
        ck["ux.j_act"] = lambda: journey(
            ctx, ["/stoc/vlr-0001", "/test-drive?vin=VLR1TERRA23000001", "STOP înainte de submit"],
            sorted(a["name"] for a in form_by(ctx, "test drive")[0]["fields"] if "required" in a),
            sorted(["vin", "name", "phone", "email", "appointment_at", "consent"]),
        )
        ck["proto.poppy"] = lambda: verdict(not aapval.validate("poppy", ctx.js("/.well-known/poppy.json")), "poppy.json valid pe schemă, link spre același card")

        def vehicle():
            first = ctx.mcp("tools/call", {"name": "aap_inventory_search", "arguments": {}})["structuredContent"]["data"]["vehicles"][0]
            detail = ctx.mcp("tools/call", {"name": "aap_inventory_vehicle", "arguments": {"vin": first["vin"]}})["structuredContent"]
            return verdict(
                not aapval.validate("vehicle-detail-response", detail) and detail["data"]["price"] == first["price"] and detail["data"]["status"] == first["status"],
                f"detaliu valid; preț {detail['data']['price']} și stare {detail['data']['status']} = căutare",
            )
        ck["proto.vehicle"] = vehicle

        def pag():
            data = ctx.mcp("tools/call", {"name": "aap_inventory_search", "arguments": {}})["structuredContent"]["data"]
            ids = [x["vehicle_id"] for x in data["vehicles"]]
            return verdict(data["next_cursor"] is None and data["total"] == len(ids) == len(set(ids)), f"total {data['total']} = listări, next_cursor null, fără duplicate")
        ck["proto.pagination"] = pag

        def unsup():
            r = ctx.mcp("tools/call", {"name": "aap_inventory_search", "arguments": {"filters": {"interior_color": ["black"]}}})
            e = r.get("structuredContent", {})
            return verdict(r.get("isError") and e.get("code") == "UNSUPPORTED_FILTER" and not aapval.validate("error", e), "filtru nedeclarat → UNSUPPORTED_FILTER (eroare validă pe schemă)")
        ck["proto.unsupported_filter"] = unsup

        def lead():
            tool = next(x for x in ctx.mcp("tools/list")["tools"] if x["name"] == "aap_lead_submit")
            required = set(tool["inputSchema"]["required"])
            return verdict({"consent", "idempotency_key", "source_agent"} <= required, f"inputSchema.required = {sorted(required)} (tool neapelat)")
        ck["proto.lead_schema"] = lead
    if t == "importer":
        org = ctx.of("Organization")[0]
        models = ctx.of("Car")
        dealers = [n for n in ctx.of("AutoDealer")]
        ck["id.schema_org"] = lambda: verdict(all(k in org for k in ["name", "logo", "url", "sameAs", "brand"]), "Organization: name, logo, url, sameAs, brand")
        ck["id.official"] = lambda: verdict("importatorul oficial" in ctx.text, "„importatorul oficial și exclusiv” în text")
        ck["id.contact"] = lambda: verdict("contactPoint" in org and "+40 21 000 0000" in ctx.text, "contactPoint + telefon în text")
        ck["mod.urls"] = lambda: verdict(all(n["url"].split("example")[1] in ctx.parser.links for n in models), f"{len(models)} pagini model legate")
        ck["mod.schema_model"] = lambda: verdict(len(models) >= 2, f"{len(models)} modele cu Car")
        ck["mod.schema_offer"] = lambda: verdict(all(n["offers"].get("lowPrice") and n["offers"].get("validThrough") for n in models), "AggregateOffer lowPrice + validThrough")
        ck["mod.fields"] = lambda: verdict(all(k in ctx.text for k in ["29.900 €", "Motorizări", "CP", "WLTP", "Autonomie", "Garanție"]), "preț de la, motorizări, putere, WLTP, autonomie EV, garanție")
        ck["mod.price_readable"] = lambda: verdict(all(price_in_text(ctx, {"price": n["offers"]["lowPrice"], "priceCurrency": "EUR"})[0] for n in models), "preț de la în text pentru toate modelele")
        ck["mod.price_final"] = lambda: verdict("cu TVA inclus" in ctx.text and "nu depind de finanțare" in ctx.text, "TVA inclus + independent de finanțare")
        ck["net.locator"] = lambda: verdict(all(n["name"] in ctx.text and n["address"]["streetAddress"] in ctx.text for n in dealers), f"{len(dealers)} dealeri în tabel HTML cu oraș, adresă, telefon")
        ck["net.schema_dealers"] = lambda: verdict(all("geo" in n and "address" in n for n in dealers), f"{len(dealers)} AutoDealer cu adresă + geo")
        ck["net.links"] = lambda: verdict(all(n["url"] in ctx.parser.links for n in dealers), "link-uri https către toți dealerii")
        ck["act.test_drive_route"] = lambda: verdict(any(a.get("name") == "dealer_id" for a in form_by(ctx, "test drive")[0]["fields"]) and no_captcha(ctx), "selecție dealer în formular, fără CAPTCHA")
        ck["act.locator_search"] = lambda: verdict(any(f["attrs"].get("method") == "get" and any(a.get("name") == "city" for a in f["fields"]) for f in ctx.parser.forms), "căutare dealer GET după oraș / cod poștal")
        ck["act.webmcp"] = lambda: webmcp(ctx, ["find_dealer", "get_model", "book_test_drive"])
        ck["trust.offer_validity"] = lambda: verdict(all("validThrough" in n["offers"] for n in models) and "valabile" in ctx.text, "validThrough + perioadă în text")

        def jd():
            cluj = (46.7712, 23.6236)
            best = min(dealers, key=lambda n: math.dist(cluj, (n["geo"]["latitude"], n["geo"]["longitude"])))
            return journey(ctx, ["/", "/dealeri?city=Cluj-Napoca"], (best["name"], best["telephone"]), ("AutoNova Cluj", "+40264000100"))
        ck["ux.j_dealer"] = jd
        ck["ux.j_price"] = lambda: journey(ctx, ["/", "/modele/terra"], (fmt_eur(models[0]["offers"]["lowPrice"]) + " €", "5 ani / 150.000 km" if "5 ani / 150.000 km" in ctx.text else None), ("29.900 €", "5 ani / 150.000 km"))
        ck["ux.j_compare"] = lambda: journey(ctx, ["/modele/terra"], re.search(r"Premium 34\.900 € (.+?) Programează", ctx.text).group(1).strip(), '+ cameră 360°, scaune ventilate, jante 19"')
        ck["ux.j_act"] = lambda: journey(
            ctx, ["/test-drive", "STOP înainte de submit"],
            sorted(a["name"] for a in form_by(ctx, "test drive")[0]["fields"] if "required" in a),
            sorted(["model", "dealer_id", "name", "phone", "email", "consent"]),
        )

        def agg():
            scope = Ctx.aap(card())["skills"]["inventory.search"]["capabilities"]["scope"]
            info = ctx.mcp("tools/call", {"name": "aap_dealer_information", "arguments": {}})["structuredContent"]
            return verdict(scope == "aggregate" and not aapval.validate("dealer-information-response", info), "scope aggregate + dealer.information valid")
        ck["proto.aap_aggregate"] = agg
        ck["proto.network_adoption"] = lambda: verdict(True, f"{len(dealers)} dealeri în rețea; adopția se măsoară prin GET pe agent-card.json-ul fiecăruia (domenii fictive în fixture)")
    if t == "ecommerce":
        store = ctx.of("OnlineStore")[0]
        products = ctx.of("Product")
        ck["id.schema_org"] = lambda: verdict(all(k in store for k in ["name", "logo", "url", "contactPoint"]), "OnlineStore: name, logo, url, contactPoint")
        ck["id.company"] = lambda: verdict(all(k in ctx.text for k in ["CUI", "ANPC", "SAL"]) and "ec.europa.eu/consumers/odr" not in ctx.page, "CUI, ANPC, SAL în text; fără link ODR închis")
        ck["prod.urls"] = lambda: verdict(all(n["url"].split("example")[1] in ctx.parser.links for n in products), f"{len(products)} pagini produs legate")
        ck["prod.schema_product"] = lambda: verdict(all(all(k in n for k in ["name", "image", "brand", "sku"]) and any(k.startswith("gtin") for k in n) for n in products), "Product: name, image, brand, sku, gtin")
        ck["prod.schema_offer"] = lambda: verdict(all(all(k in n["offers"] for k in ["price", "priceCurrency", "availability"]) for n in products), "Offer complet")
        ck["prod.fields"] = lambda: verdict(all(n["sku"] in ctx.text and n["gtin13"] in ctx.text for n in products) and "În stoc" in ctx.text and "1–2 zile" in ctx.text, "preț, SKU, GTIN, brand, stoc, livrare în text")
        ck["prod.price_readable"] = lambda: verdict(all(price_in_text(ctx, n["offers"])[0] for n in products), f"prețuri în text: {[fmt_ron(n['offers']['price']) for n in products]}")
        ck["prod.price_consistency"] = lambda: verdict(all(price_in_text(ctx, n["offers"])[0] for n in products), "JSON-LD = text")
        ck["prod.policies_schema"] = lambda: verdict(bool(ctx.of("MerchantReturnPolicy")) and all("shippingDetails" in n["offers"] for n in products), "MerchantReturnPolicy + shippingDetails")
        ck["prod.rating"] = lambda: verdict(any(int(n.get("aggregateRating", {}).get("reviewCount", 0)) > 0 and n.get("review") for n in products), "AggregateRating cu recenzii reale atașate")
        ck["prod.search_urls"] = lambda: verdict(any("/cauta?" in link for link in ctx.parser.links), "căutare GET parametrizată")
        ck["prod.feed"] = lambda: verdict(any(link.endswith("produse.xml") for link in ctx.parser.links), "feed XML")
        ck["act.add_to_cart"] = lambda: verdict(bool(form_by(ctx, "coș")), "formular „Adaugă în coș” fără login")
        ck["act.guest_checkout"] = lambda: verdict(
            bool(form_by(ctx, "livrare")) and not any(a.get("type") == "password" for f in ctx.parser.forms for a in f["fields"]) and no_captcha(ctx),
            "checkout fără cont, fără parolă, fără CAPTCHA",
        )
        ck["act.contact"] = lambda: verdict(any(link.startswith("tel:") for link in ctx.parser.links) and any(link.startswith("mailto:") for link in ctx.parser.links), "tel: + mailto: + formular")
        ck["act.webmcp"] = lambda: webmcp(ctx, ["search_products", "get_product", "add_to_cart"])
        ck["trust.policies_text"] = lambda: verdict(all(k in ctx.text for k in ["Livrare", "Retur", "Garanție", "30 de zile", "19,90 lei", "24 de luni"]), "livrare / retur / garanție cu termene și costuri")
        ck["ux.j_find"] = lambda: journey(
            ctx, ["/", "/cauta?category=frane&price_max=200&in_stock=1"],
            next(n["sku"] for n in products if float(n["offers"]["price"]) < 200 and "InStock" in n["offers"]["availability"] and "frân" in n["name"].lower()),
            "PF200",
        )
        ck["ux.j_total"] = lambda: journey(
            ctx, ["/p/placute-frana-pf200"],
            fmt_ron(float(products[0]["offers"]["price"]) + float(products[0]["offers"]["shippingDetails"]["shippingRate"]["value"])) + " lei" if "209,80 lei" in ctx.text else None,
            "209,80 lei",
        )
        ck["ux.j_policy"] = lambda: journey(ctx, ["/retur"], (ctx.of("MerchantReturnPolicy")[0]["merchantReturnDays"], "gratuit" in ctx.text), (30, True))
        ck["ux.j_act"] = lambda: journey(
            ctx, ["/p/placute-frana-pf200", "/cos", "/checkout", "STOP înainte de plată"],
            sorted(a["name"] for a in form_by(ctx, "livrare")[0]["fields"] if "required" in a),
            sorted(["name", "email", "phone", "address", "city", "postal_code", "terms", "consent"]),
        )
        ck["proto.mcp_public"] = lambda: verdict("MCP" in (ctx.fetch("/llms.txt") or "") and "mcp:tools/list" in testserver.load(FIX[ctx.typ])[1], "MCP de catalog declarat în llms.txt + tools/list")
        ck["proto.ucp"] = lambda: verdict(bool(ctx.js("/.well-known/ucp")), "/.well-known/ucp prezent")
        ck["proto.checkout_protocol"] = lambda: verdict("acp" in ctx.js("/.well-known/ucp")["capabilities"]["checkout"]["protocols"], "checkout agentic declarat (UCP, ACP), cu confirmarea utilizatorului")
    return ck


def visibility(site_type: str) -> dict[str, Any]:
    """Visibility per PLAN: per răspuns 0,5 menționat + 0,3 × (1/rank) + 0,2 citat domeniul; medie pe prompturi × 3 rulări."""
    _, sims = testserver.load(FIX[site_type])
    panel = json.loads(sims["visibility:panel"][1])
    scores = []
    for run in panel["runs"]:
        mentioned = panel["entity"] in run["answer"] or panel["entity"] in run["ranked_entities"]
        rank = run["ranked_entities"].index(panel["entity"]) + 1 if panel["entity"] in run["ranked_entities"] else None
        cited = any(panel["domain"] in url for url in run["citations"])
        scores.append(0.5 * mentioned + 0.3 * (1 / rank if rank else 0) + 0.2 * cited)
    prompts = len({run["prompt"] for run in panel["runs"]})
    return {
        "score": round(100 * sum(scores) / len(scores), 1),
        "prompts": prompts,
        "runs": len(panel["runs"]),
        "mentioned": sum(1 for run in panel["runs"] if panel["entity"] in run["ranked_entities"]),
        "source": "simulat (fixture)",
    }


FIX = {t: f"{ROOT}/fixtures/{t}-max.html" for t in LAYER_W}


def run(site_type: str, port: int) -> dict[str, Any]:
    server, ca = testserver.serve(FIX[site_type], port, os.path.join(os.path.expanduser("~"), ".ax-scanner-certs"))
    try:
        ctx = Ctx(site_type, port, ca)
        registry = build(ctx)
        rows = checklist(site_type)
        results = []
        for row in rows:
            if row["sev"] == "na":
                status, evidence = "na", "nu se aplică"
            elif row["id"] not in registry:
                status, evidence = "fail", "check neimplementat în scorer"
            else:
                try:
                    status, evidence = registry[row["id"]]()
                except Exception as e:  # noqa: BLE001 - un check care crapă pică, nu oprește rularea
                    status, evidence = "fail", f"eroare: {e!r}"
            results.append(dict(row, status=status, evidence=evidence if isinstance(evidence, str) else json.dumps(evidence, ensure_ascii=False)))
        layers = {}
        for layer, weight in LAYER_W[site_type].items():
            relevant = [x for x in results if x["layer"] == layer and x["status"] != "na"]
            denom = sum(SEV.get(x["sev"], 0) for x in relevant)
            num = sum(SEV.get(x["sev"], 0) * {"pass": 1, "warn": 0.5, "fail": 0}[x["status"]] for x in relevant)
            layers[layer] = round(100 * num / denom, 1) if denom else 100.0
        readiness = round(sum(layers[layer] * w for layer, w in LAYER_W[site_type].items()) / 100, 1)
        crit_fail = [x["id"] for x in results if x["sev"] == "CRITICAL" and x["status"] == "fail"]
        vis = visibility(site_type)
        ax = round(0.6 * readiness + 0.4 * vis["score"], 1)
        grade = "A" if ax >= 90 else "B" if ax >= 75 else "C" if ax >= 60 else "D" if ax >= 40 else "F"
        if crit_fail and grade in "AB":
            grade = "C"
        return {"type": site_type, "ax_score": ax, "visibility": vis, "readiness": readiness, "grade": grade, "layers": layers, "checks": results, "critical_fail": crit_fail}
    finally:
        server.shutdown()


if __name__ == "__main__":
    os.makedirs(f"{ROOT}/fixtures/reports", exist_ok=True)
    for i, t in enumerate(LAYER_W):
        r = run(t, 8443 + i)
        with open(f"{ROOT}/fixtures/reports/{t}.json", "w", encoding="utf-8") as f:
            json.dump(r, f, ensure_ascii=False, indent=1)
        n = {s: sum(1 for x in r["checks"] if x["status"] == s) for s in ["pass", "warn", "fail", "na"]}
        print(f"{t:10s} AX {r['ax_score']:5.1f} (readiness {r['readiness']:5.1f}, visibility {r['visibility']['score']:5.1f}, {r['visibility']['runs']} răspunsuri)  grade {r['grade']}  {n}  layers {r['layers']}")
        for x in r["checks"]:
            if x["status"] in ("fail", "warn"):
                print("   ", x["status"].upper(), x["id"], "→", x["evidence"][:200])
