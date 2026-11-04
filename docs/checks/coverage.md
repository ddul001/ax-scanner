# Trasabilitate: element identificat → check

| Element identificat | Sursă | Check(uri) | Tipuri |
|---|---|---|---|
| Boți AI extinși (9 UA) | plan inițial | disc.robots_ai | toate |
| Blocare WAF per UA | plan inițial | disc.waf_ua | toate |
| Conținut fără JS | plan inițial, PLAN | disc.no_js, ux.agent_vs_human | toate |
| llms.txt (+ URL MCP) | SPEC, AAP DISC-05 | disc.llms_txt, proto.consistency | toate |
| well-known api-catalog / OAuth | plan inițial | disc.wellknown (INFO) | toate |
| schema.org AutoDealer / Car / Offer | SPEC, plan inițial | id.schema_dealer, inv.schema_* | dealer |
| NAP, sameAs, hreflang | plan inițial | id.nap, id.same_as, id.lang | toate |
| Preț în imagine (vision) | PLAN | *.price_readable | toate |
| Coerență preț JSON-LD / AAP | AAP SEO-02 | inv.price_consistency | dealer, ecom |
| Preț final / out-the-door | plan inițial, AAP price rules | inv.price_final, mod.price_final | dealer, importator |
| Prospețime stoc | AAP INV-03 | inv.freshness | dealer |
| Dotări cu dovezi | AAP feature_evidence | inv.features | dealer |
| Coerență cu marketplace-uri | strategie produs | inv.marketplace (INFO, post-MVP) | dealer |
| Formulare completabile / WebMCP declarativ | plan inițial | act.forms_semantic | toate |
| WebMCP tools | plan inițial, AAP WEB-01 | act.webmcp (INFO) | toate |
| Trust: injection, HTTPS, cookie, priceValidUntil | plan inițial | trust.* | toate |
| GDPR / consent | AAP consent, profil EU | trust.gdpr | toate |
| Agent Journey (Shopper Agent, bonus agentic) | plan inițial, hackathon | ux.j_* | toate |
| Agent vs Human view | plan inițial | ux.agent_vs_human | toate |
| AAP descoperire (card, poppy) | AAP DISC-01..06 | proto.aap_card, proto.aap_version, proto.poppy, proto.consistency | dealer, importator |
| AAP MCP | AAP MCP-01..03 | proto.mcp, proto.tools | dealer, importator |
| AAP inventar | AAP INV-01..07 | proto.search, proto.vehicle, proto.pagination, proto.unsupported_filter | dealer, importator |
| AAP lead (fără apel) | AAP LEAD-01/02 | proto.lead_schema | dealer |
| Fresh agent onboarding < 60 s | AAP ONB-01 | proto.onboarding | dealer |
| AAP aggregate | AAP exemple aggregate | proto.aap_aggregate | importator |
| Adopție AAP în rețea | strategie produs | proto.network_adoption (INFO) | importator |
| Profil AAP-EU | specificația AAP | proto.eu_profile (INFO) | dealer, importator |
| DMC-12 / UCP | strategie produs | proto.ucp (INFO) | toate |
| Server MCP catalog / ACP | specificația AAP | proto.mcp_public, proto.checkout_protocol | ecom |
| Site-uri mixte | PLAN (întrebare deschisă) | README §6 | toate |
| Visibility (prompt panel) | PLAN | în afara readiness, 0,4 din AX | toate |

## Lăsate intenționat în afara hackathonului
| Element | Motiv |
|---|---|
| Ambele revizii MCP obligatorii (MCP-02) | bonus în proto.mcp, nu check separat |
| INV-08 dotări cu dovezi AAP, INV-09 geo | INFO, adopție zero |
| Agent Traffic Detector, Web Bot Auth (RFC 9421) | post-MVP |
| Monitoring, badge, analytics competitive | post-MVP |
| Trimitere lead / ADF | interzis prin regulile de siguranță |
