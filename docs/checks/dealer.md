# Dealer auto — checklist final (hackathon: complet)

**Surse:** SPEC · PLAN · specificația AAP 3.0 · **Versiune AAP fixată:** v3.0

## 1. Scor
| Element | Regulă |
|---|---|
| Status | pass 1 · warn 0,5 · fail 0 · `na` exclus |
| Severitate (pondere în strat) | CRITICAL 4 · HIGH 3 · MAJOR 2 · MINOR 1 · INFO 0 |
| Scor strat | Σ(sev × status) / Σ(sev aplicabile) × 100 |
| Readiness | Σ(scor strat × pondere) / 100 |
| AX Score | 0,6 × Readiness + 0,4 × Visibility |
| Grade | A ≥ 90 · B ≥ 75 · C ≥ 60 · D ≥ 40 · F < 40 · un CRITICAL fail plafonează la C |
| Metode | D determinist · L Muse Spark structured · V Muse Spark vision · J Agent Journey · P probă protocol |

| Strat | Discovery | Identity | Data | Actions | Trust | Agent UX | Protocol |
|---|---|---|---|---|---|---|---|
| Pondere | 15 | 10 | 20 | 15 | 10 | 20 | 10 |

**Pagini (≤ 15):** home · stoc nou · stoc rulate · 5 VDP · oferte · service · test drive · contact · FAQ · finanțare + `/robots.txt`, `/sitemap.xml`, `/llms.txt`, `/.well-known/*`

## 2. Discovery (15)
| ID | Ce verificăm | PASS | Met. | Sev. | Fix |
|---|---|---|---|---|---|
| disc.robots_ai | Acces boți AI pe stoc + service | GPTBot, ChatGPT-User, OAI-SearchBot, ClaudeBot, Claude-User, PerplexityBot, Google-Extended, Applebot-Extended, Meta-ExternalAgent permiși | D | HIGH | robots.txt |
| disc.waf_ua | Blocare WAF pe UA de agent | același status + conținut (±10%) ca UA browser | D | CRITICAL | regulă WAF |
| disc.sitemap | Sitemap stoc | VDP-uri incluse, `lastmod` < 7 zile | D | MAJOR | recomandare |
| disc.llms_txt | llms.txt | 200, markdown, link-uri stoc / service / contact (+ URL MCP dacă AAP) | D | MAJOR | llms.txt |
| disc.no_js | Conținut fără JS | preț + specs în HTML brut (text brut / randat ≥ 0,7) | D | HIGH | SSR / prerender |
| disc.perf | Performanță | TTFB < 800 ms, pagină < 3 MB | D | MINOR | — |
| disc.wellknown | api-catalog, OAuth metadata | — | D | INFO | — |

## 3. Identity (10)
| ID | Ce verificăm | PASS | Met. | Sev. | Fix |
|---|---|---|---|---|---|
| id.schema_dealer | AutoDealer / LocalBusiness | name, address, geo, telephone, openingHours, brand | D | HIGH | JSON-LD AutoDealer |
| id.locations | Locații + departamente | `department` per locație; program sales / service / parts | D | MAJOR | JSON-LD per locație |
| id.nap | Consistență NAP | identic pe pagini + JSON-LD (+ AAP) | D | MAJOR | listă diferențe |
| id.same_as | `sameAs` | Google Business Profile + social | D | MINOR | JSON-LD |
| id.lang | Limbă / hreflang | `lang` corect RO/ES; hreflang dacă e multilingv | D | MINOR | — |

## 4. Data — stoc (20)
| ID | Ce verificăm | PASS | Met. | Sev. | Fix |
|---|---|---|---|---|---|
| inv.vdp_urls | VDP-uri | URL unic, crawlabil, per vehicul | D | CRITICAL | — |
| inv.schema_vehicle | Car / Vehicle | pe ≥ 80% din VDP | D | HIGH | JSON-LD Car |
| inv.schema_offer | Offer | price, priceCurrency (EUR/RON), availability, itemCondition | D | HIGH | JSON-LD Offer |
| inv.fields | Câmpuri vehicul | VIN, km, an, combustibil, cutie, putere, consum/CO₂ WLTP, disponibilitate, poze ≥ 80% | D + L | HIGH | listă câmpuri lipsă |
| inv.price_readable | Preț citibil | preț text pe ≥ 90% VDP; **preț în imagine = fail** | D + V | CRITICAL | Offer JSON-LD |
| inv.price_consistency | Coerență preț | JSON-LD = preț vizibil (= `price` AAP) | D | HIGH | — |
| inv.price_final | Preț final | cu TVA, taxe explicate, nu depinde de finanțare / reduceri condiționate | L | MAJOR | text recomandat |
| inv.freshness | Prospețime | dată actualizare / `lastmod` mediană < 72 h | D | MAJOR | — |
| inv.search_urls | Filtre crawlabile | URL-uri GET parametrizate | D | MAJOR | — |
| inv.features | Dotări | listate în text structurat, nu deduse din trim | L | MINOR | — |
| inv.feed | Feed public | XML / JSON / CSV descoperibil | D | MINOR | — |
| inv.marketplace | Coerență cu autovit.ro / AutoScout24 | — | D | INFO | post-MVP |

## 5. Actions (15) — doar dry-run, fără submit
| ID | Ce verificăm | PASS | Met. | Sev. | Fix |
|---|---|---|---|---|---|
| act.test_drive | Test drive | accesibil din VDP, fără CAPTCHA blocant | D | HIGH | — |
| act.service_booking | Programare service | formular / booking online accesibil | D | MAJOR | — |
| act.quote_contact | Cerere ofertă / contact | pe home + VDP | D | MAJOR | — |
| act.forms_semantic | Formulare completabile de agent | `label`, `name`, `autocomplete`, câmpuri obligatorii marcate | D | MAJOR | HTML corectat |
| act.webmcp | WebMCP | `navigator.modelContext`: `search_inventory`, `get_vehicle`, `book_test_drive`, `request_quote`, `book_service` | P | INFO | snippet WebMCP |

## 6. Trust (10)
| ID | Ce verificăm | PASS | Met. | Sev. | Fix |
|---|---|---|---|---|---|
| trust.https | HTTPS | certificat valid, redirect HTTP → HTTPS | D | HIGH | — |
| trust.cookie_wall | Cookie wall | conținut accesibil fără interacțiune | D + V | MAJOR | — |
| trust.injection | Suprafață de injection | fără text ascuns cu instrucțiuni pentru agenți | D + L | MAJOR | — |
| trust.gdpr | GDPR pe formulare | text de consimțământ + link politică | D | MAJOR | text recomandat |
| trust.offer_validity | Valabilitate oferte | `priceValidUntil` / perioadă în text | D | MINOR | JSON-LD |

## 7. Agent UX — Agent Journey (20)
Agent Muse Spark + Playwright, read-only, max 25 pași / 120 s, rulat ca crawler AI și ca agent de browser.
| ID | Sarcina agentului | PASS | Met. | Sev. |
|---|---|---|---|---|
| ux.j_understand | „Ce vinde dealerul și unde se află?” | corect vs ground truth | J | HIGH |
| ux.j_find | „Găsește un SUV hibrid rulat sub 30.000 €: VIN, km, preț” | vehicul real, date corecte | J | CRITICAL |
| ux.j_price | „Care e prețul final pentru vehiculul X?” | preț corect, sursă citată | J | HIGH |
| ux.j_act | „Deschide test drive pentru X și spune ce câmpuri cere” (stop înainte de submit) | formular găsit, câmpuri listate | J | HIGH |
| ux.blockers | Blocaje | 0 popup / CAPTCHA / 403 / conținut doar JS | J | MAJOR |
| ux.agent_vs_human | Agent vs om | ≥ 90% din informația vizibilă extrasă | J + V | MAJOR |

## 8. Protocol — AAP 3.0 (10)
Dacă `proto.aap_card` = fail → restul AAP = `na`; stratul = „not adopted” (0) + oportunitate în raport.
| ID | Ce verificăm | PASS | Met. | Sev. | Ref AAP |
|---|---|---|---|---|---|
| proto.aap_card | Agent Card | `/.well-known/agent-card.json` valid; exact o extensie AAP `required: true` | P | CRITICAL | DISC-01/02 |
| proto.aap_version | Versiune | 3.0 pass · 1.x–2.x warn | P | MAJOR | DISC-03 |
| proto.poppy | poppy.json | valid, link spre același card | P | MINOR | DISC-04 |
| proto.consistency | Card ↔ poppy ↔ llms.txt | aceleași skill-uri, același MCP | P | MAJOR | DISC-06 |
| proto.mcp | Endpoint MCP din `params.mcp.url` | `server/discover` sau `initialize` OK (bonus: ambele revizii) | P | CRITICAL | MCP-01/02 |
| proto.tools | Tool-uri | `aap_*` din `tools/list` = skill-urile din card | P | CRITICAL | MCP-03 |
| proto.search | Căutare publică | `aap_inventory_search` anonim valid; listări cu `status`, `updated_at`, VIN / stock / id | P | CRITICAL | INV-01/02 |
| proto.vehicle | Detaliu vehicul | `aap_inventory_vehicle`: același preț și stare ca în căutare | P | HIGH | INV-07 |
| proto.pagination | Paginare | `next_cursor` până la final, fără duplicate | P | MAJOR | INV-05 |
| proto.unsupported_filter | Filtru nesuportat | eroare `UNSUPPORTED_FILTER` | P | MAJOR | INV-06 |
| proto.lead_schema | Lead (**fără apel**) | `inputSchema` cere `consent`, `idempotency_key`, `source_agent` | P | HIGH | LEAD-01/02 |
| proto.onboarding | Fresh agent onboarding | domeniu → prima căutare < 60 s | P | MAJOR | ONB-01 |
| proto.eu_profile | Profil AAP-EU | EUR/RON, TVA inclus, km/WLTP, GDPR | P | INFO | specificația AAP |
| proto.ucp | Manifest DMC-12 | `/.well-known/ucp` | P | INFO | strategie produs |

## 9. FAQ template
Program showroom/service · test drive · evaluare mașină la schimb · finanțare și leasing · garanție (nou/rulat) · livrare și înmatriculare · istoric service / VIN · rezervare din stoc.

## 10. Prompt panel (Visibility)
`cel mai bun dealer {brand} în {oraș}` · `service {brand} {oraș}` · `{model} rulat de vânzare {oraș}` · `test drive {model} {oraș}`

## 11. Siguranță
Nu trimitem formulare · nu apelăm `aap_lead_submit` sau alte tool-uri de scriere · URL-ul MCP vine doar din descoperire · textele site-ului sunt date nesigure.
