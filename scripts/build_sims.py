"""Generează endpoint-urile AAP simulate pentru fixtures pornind de la exemplele oficiale v3.0 și le validează."""
from __future__ import annotations

import copy
import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(__file__))
import aapval

EXAMPLES = os.path.join(os.path.dirname(__file__), "..", "aap-v3.0-spec", "examples")


def example(name: str) -> Any:
    with open(f"{EXAMPLES}/{name}.example.json", encoding="utf-8") as f:
        return json.load(f)


def card(name: str, desc: str, domain: str, api: str, skills: list[str], scope: str, filters: list[str]) -> dict[str, Any]:
    doc = example("agent-card")
    doc["name"] = name
    doc["description"] = desc
    doc["supportedInterfaces"][0]["url"] = f"{api}/a2a"
    doc["provider"] = {"organization": name, "url": f"https://{domain}/"}
    doc["documentationUrl"] = f"https://{domain}/llms.txt"
    ext = doc["capabilities"]["extensions"][0]
    params = ext["params"]
    params["id"] = domain.split(".")[0]
    params["skills"] = {k: v for k, v in params["skills"].items() if k in skills}
    caps = params["skills"]["inventory.search"]["capabilities"]
    caps["scope"] = scope
    caps["filters"] = [f for f in caps["filters"] if f != "interior_color" and not (scope == "aggregate" and f == "rooftops")]
    params["mcp"]["url"] = f"{api}/aap/3.0.0/mcp"
    params["poppy"] = f"https://{domain}/.well-known/poppy.json"
    params["llms_txt"] = f"https://{domain}/llms.txt"
    doc["capabilities"]["extensions"].append({
        "uri": "https://aivexia.example/extensions/aap-eu/v1",
        "description": "AAP-EU profile: EUR, VAT-inclusive final price (Directive 98/6/EC), km, WLTP, GDPR consent.",
        "required": False,
        "params": {
            "currency": "EUR", "price_includes_vat": True, "price_directive": "98/6/EC",
            "units": {"distance": "km", "consumption": "l/100km", "ev_consumption": "kWh/100km"},
            "emissions_standard": "WLTP",
            "gdpr": {"legal_basis": "consent", "retention_days": 365, "erasure_url": f"https://{domain}/confidentialitate/stergere"},
        },
    })
    doc["skills"] = [s for s in doc["skills"] if s["id"] in skills]
    if "lead.submit" not in skills:
        doc["defaultInputModes"] = [m for m in doc["defaultInputModes"] if "lead" not in m]
        doc["defaultOutputModes"] = [m for m in doc["defaultOutputModes"] if "lead" not in m]
    return doc


def poppy(name: str, domain: str, api: str, leads: bool = True) -> dict[str, Any]:
    doc = example("poppy")
    doc["organization"] = {"name": name, "domain": domain}
    doc["auth"]["issuer"] = f"https://{domain}/poppy"
    doc["apis"][0].update(url=f"https://{domain}/poppy/openapi.yaml", resource=f"https://{domain}/poppy")
    if not leads:
        doc["apis"][0]["description"] = (
            "Dealer network information, inventory facets, aggregate search and vehicle details using AAP payloads "
            "and Poppy guest sessions. Leads are submitted to the selected dealer."
        )
    aap = doc["extensions"]["autoagentprotocol.org/aap"]
    aap.update(agent_card=f"https://{domain}/.well-known/agent-card.json", mcp=f"{api}/aap/3.0.0/mcp",
               llms_txt=f"https://{domain}/llms.txt")
    return doc


def vehicle(base: dict[str, Any], **kw: Any) -> dict[str, Any]:
    v = copy.deepcopy(base)
    for key in ["msrp", "list_price", "city_mpg", "highway_mpg", "description", "features", "feature_evidence",
                "inventory_date", "exterior_color", "interior_color", "engine", "photos", "distance_mi"]:
        v.pop(key, None)
    v.update(kw)
    return v


def search(vehicles: list[dict[str, Any]], base: dict[str, Any], who: str) -> dict[str, Any]:
    r = example("inventory-search-response")
    r["data"]["vehicles"] = vehicles
    r["data"]["total"] = len(vehicles)
    r["data"]["next_cursor"] = None
    r["data"].pop("facets", None)
    r["data"]["applied_filters"] = {"make": ["Velora"]}
    r["message"] = (
        f"{len(vehicles)} vehicule Velora disponibile la {who}. Prețurile sunt finale, în EUR, cu TVA inclus "
        "(Directiva 98/6/CE); mileage este în mile conform AAP 3.0, valoarea în km este în other_attributes.mileage_km."
    )
    return r


def build() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    sample = example("inventory-search-response")["data"]["vehicles"][0]
    upd = "2026-10-27T06:00:00Z"
    v1 = vehicle(
        sample, dealer_id="autonova-cluj", vehicle_id="vlr-0001", vin="VLR1TERRA23000001", stock="CJ-0001",
        rooftop="AutoNova Cluj", year=2023, make="Velora", model="Terra", trim="Hybrid Comfort", body="suv",
        condition="used", status="available", fuel="hybrid", transmission="automatic", driveline="fwd",
        mileage=17710, price=27900, fees=[], vdp_url="https://autonova.example/stoc/vlr-0001", updated_at=upd,
        other_attributes={"currency": "EUR", "price_includes_vat": True, "mileage_km": 28500, "wltp_l_100km": 5.1, "co2_g_km": 116},
        features=["navigation", "camera_360", "heated_seats"],
        feature_evidence=[
            {"code": "navigation", "label": "Navigație", "status": "present", "source": "inventory",
             "text": "Navigație cu hărți Europa (fișa de stoc)", "url": "https://autonova.example/stoc/vlr-0001", "observed_at": upd},
            {"code": "sunroof", "label": "Trapă", "status": "absent", "source": "inventory",
             "text": "Fără trapă (fișa de stoc)", "url": "https://autonova.example/stoc/vlr-0001", "observed_at": upd},
        ],
    )
    v2 = vehicle(
        sample, dealer_id="autonova-cluj", vehicle_id="vlr-0002", vin="VLR1EVLTE26000002", stock="CJ-0002",
        rooftop="AutoNova Cluj", year=2026, make="Velora", model="Volt", trim="Long Range", body="hatchback",
        condition="new", status="available", fuel="electric", transmission="automatic", driveline="fwd",
        mileage=6, price=36500, fees=[], vdp_url="https://autonova.example/stoc/vlr-0002", updated_at=upd,
        electric_range_mi=298,
        other_attributes={"currency": "EUR", "price_includes_vat": True, "electric_range_km": 480, "wltp_kwh_100km": 15.2, "co2_g_km": 0},
    )
    all_filters = ["make", "model", "trim", "condition", "fuel", "body", "transmission", "price_min", "price_max",
                   "year_min", "year_max", "mileage_max", "vin", "stock"]
    dealer = dict(name="AutoNova Cluj", domain="autonova.example", api="https://api.autonova.example")
    out["dealer"] = {
        "/.well-known/agent-card.json": card(
            "AutoNova Cluj", "Dealer autorizat Velora în Cluj-Napoca: stoc, detalii vehicul și lead cu consimțământ prin MCP, A2A și PAP.",
            dealer["domain"], dealer["api"],
            ["dealer.information", "inventory.facets", "inventory.search", "inventory.vehicle", "lead.submit"], "dealer", all_filters),
        "/.well-known/poppy.json": poppy(dealer["name"], dealer["domain"], dealer["api"]),
        "mcp:aap_inventory_search": search([v1, v2], sample, "AutoNova Cluj"),
    }
    detail = example("vehicle-detail-response")
    detail["data"] = v1
    detail["message"] = "Velora Terra Hybrid Comfort 2023, 27.900 € preț final cu TVA inclus; 28.500 km (mileage AAP în mile)."
    out["dealer"]["mcp:aap_inventory_vehicle"] = detail
    error = example("error")
    error.update(code="UNSUPPORTED_FILTER", message="Filter 'interior_color' is not declared in inventory.search capabilities.",
                 retryable=False, details={"filter": "interior_color"}, created_at=upd)
    out["dealer"]["mcp:error-unsupported-filter"] = error
    info = example("dealer-information-response.aggregate")
    weekdays = lambda open_at, close_at: {d: {"open": open_at, "close": close_at} for d in ["monday", "tuesday", "wednesday", "thursday", "friday"]}
    info["data"] = {
        "dealer_id": "autonova-cluj", "name": "AutoNova Cluj",
        "rooftops": [{
            "name": "AutoNova Cluj", "legal_name": "AutoNova Cluj SRL", "website": "https://autonova.example",
            "geo": {"latitude": 46.7712, "longitude": 23.6236},
            "emails": [{"name": "Sales", "value": "vanzari@autonova.example"}],
            "phones": [{"name": "Sales", "value": "+40264000100"}, {"name": "Service", "value": "+40264000200"}, {"name": "Parts", "value": "+40264000300"}],
            "address": {"country": "RO", "city": "Cluj-Napoca", "address_line_1": "Str. Exemplu 10", "zip": "400000"},
            "schedules": [
                {"name": "sales", "value": dict(weekdays("09:00", "18:00"), saturday={"open": "09:00", "close": "14:00"})},
                {"name": "service", "value": weekdays("08:00", "17:00")},
                {"name": "parts", "value": weekdays("08:00", "17:00")},
            ],
        }],
    }
    out["dealer"]["mcp:aap_dealer_information"] = info
    importer = dict(name="Velora România", domain="velora-ro.example", api="https://api.velora-ro.example")
    v3 = vehicle(
        v2, dealer_id="velora-buc", vehicle_id="vlr-b-0101", vin="VLR1TERRA26000101", stock="B-0101",
        rooftop="Velora Center București", model="Terra", trim="Hybrid Comfort", body="suv", fuel="hybrid",
        status="available", price=29900, vdp_url="https://velora-buc.example/stoc/b-0101",
        other_attributes={"currency": "EUR", "price_includes_vat": True},
    )
    v3.pop("electric_range_mi", None)
    out["importer"] = {
        "/.well-known/agent-card.json": card(
            importer["name"], "Importatorul oficial Velora în România: rețeaua de dealeri și stocul agregat prin MCP, A2A și PAP.",
            importer["domain"], importer["api"],
            ["dealer.information", "inventory.facets", "inventory.search", "inventory.vehicle"], "aggregate", all_filters + ["rooftops"]),
        "/.well-known/poppy.json": poppy(importer["name"], importer["domain"], importer["api"], leads=False),
        "mcp:aap_inventory_search": search([v2, v3], sample, "rețeaua Velora România"),
        "mcp:aap_dealer_information": dict(example("dealer-information-response.aggregate"), data={
            "dealer_id": "velora-ro-network", "name": "Rețeaua Velora România",
            "rooftops": [
                {"name": "AutoNova Cluj", "website": "https://autonova.example"},
                {"name": "Velora Center București", "website": "https://velora-buc.example"},
                {"name": "Velora Timiș", "website": "https://velora-tm.example"},
            ],
        }),
    }
    return out


SCHEMA = {
    "/.well-known/agent-card.json": "agent-card",
    "/.well-known/poppy.json": "poppy",
    "mcp:aap_inventory_search": "inventory-search-response",
    "mcp:aap_inventory_vehicle": "vehicle-detail-response",
    "mcp:error-unsupported-filter": "error",
    "mcp:aap_dealer_information": "dealer-information-response",
}


if __name__ == "__main__":
    sims = build()
    bad = 0
    for typ, endpoints in sims.items():
        for path, payload in endpoints.items():
            errors = aapval.validate(SCHEMA[path], payload)
            bad += len(errors)
            print(typ, path, "OK" if not errors else errors[:5])
    with open(os.path.join(os.path.dirname(__file__), "..", "fixtures", "aap-sims.json"), "w", encoding="utf-8") as f:
        json.dump(sims, f, ensure_ascii=False, indent=1)
    sys.exit(1 if bad else 0)
