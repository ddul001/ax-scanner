# Marcă / Importator — checklist final (hackathon: de bază)

**Surse:** SPEC · PLAN · specificația AAP 3.0 (scope aggregate) · **Versiune AAP fixată:** v3.0

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
| Pondere | 15 | 15 | 20 | 10 | 10 | 20 | 10 |

**Pagini (≤ 15):** home · gamă modele · 4 pagini model · oferte · dealer locator · configurator / test drive · contact · FAQ · finanțare + `/robots.txt`, `/sitemap.xml`, `/llms.txt`, `/.well-known/*`

## 2. Discovery (15)
| ID | Ce verificăm | PASS | Met. | Sev. | Fix |
|---|---|---|---|---|---|
| disc.robots_ai | Acces boți AI pe modele + oferte + locator | GPTBot, ChatGPT-User, OAI-SearchBot, ClaudeBot, Claude-User, PerplexityBot, Google-Extended, Applebot-Extended, Meta-ExternalAgent permiși | D | HIGH | robots.txt |
| disc.waf_ua | Blocare WAF pe UA de agent | același status + conținut (±10%) ca UA browser | D | CRITICAL | regulă WAF |
| disc.sitemap | Sitemap modele | pagini model + oferte, `lastmod` < 30 zile | D | MAJOR | recomandare |
| disc.llms_txt | llms.txt | 200, markdown, link-uri modele / oferte / dealeri (+ URL MCP dacă AAP) | D | MAJOR | llms.txt |
| disc.no_js | Conținut fără JS | preț de la + specs + listă dealeri în HTML brut | D | HIGH | SSR / prerender |
| disc.perf | Performanță | TTFB < 800 ms, pagină < 3 MB | D | MINOR | — |
| disc.wellknown | api-catalog, OAuth metadata | — | D | INFO | — |

## 3. Identity (15)
| ID | Ce verificăm | PASS | Met. | Sev. | Fix |
|---|---|---|---|---|---|
| id.schema_org | Organization + Brand | name, logo, url, sameAs, brand | D | HIGH | JSON-LD Organization |
| id.official | Statut oficial | importatorul și relația cu marca în țară declarate clar | L | MAJOR | text recomandat |
| id.contact | Contact central | telefon / email / adresă sediu, în text + `contactPoint` | D | MAJOR | JSON-LD |
| id.same_as | `sameAs` | social + site global al mărcii | D | MINOR | JSON-LD |
| id.lang | Limbă / hreflang | `lang` corect RO/ES; hreflang dacă e multilingv | D | MINOR | — |

## 4. Data — modele + rețea (20)
| ID | Ce verificăm | PASS | Met. | Sev. | Fix |
|---|---|---|---|---|---|
| mod.urls | Pagini model | URL unic, crawlabil, per model | D | HIGH | — |
| mod.schema_model | Car / ProductModel | pe ≥ 80% pagini model | D | HIGH | JSON-LD Car (model) |
| mod.schema_offer | Preț „de la” | AggregateOffer `lowPrice` / Offer + `validThrough` | D | HIGH | JSON-LD AggregateOffer |
| mod.fields | Câmpuri model | preț de la, motorizări, combustibil, putere, consum/CO₂ WLTP, autonomie EV, garanție ≥ 80% | D + L | HIGH | listă câmpuri lipsă |
| mod.price_readable | Preț citibil | în text, nu doar în bannere / imagini | D + V | CRITICAL | — |
| mod.price_final | Preț final | cu TVA, fără finanțare obligatorie; condiții în text | L | MAJOR | text recomandat |
| net.locator | Dealer locator citibil | listă dealeri în HTML / JSON (nume, oraș, adresă, telefon), **nu doar hartă JS** | D + L | CRITICAL | pagină listă |
| net.schema_dealers | Dealeri în JSON-LD | listă AutoDealer cu adrese + geo | D | MAJOR | JSON-LD listă AutoDealer |
| net.links | Link-uri spre site-urile dealerilor | prezente, valide (200) | D | MINOR | — |

## 5. Actions (10) — doar dry-run, fără submit
| ID | Ce verificăm | PASS | Met. | Sev. | Fix |
|---|---|---|---|---|---|
| act.test_drive_route | Test drive / configurator | accesibil, rutează spre dealer, fără CAPTCHA blocant | D | HIGH | — |
| act.locator_search | Căutare dealer | după oraș / cod poștal prin URL GET | D | MAJOR | — |
| act.forms_semantic | Formulare completabile | `label`, `name`, `autocomplete`, câmpuri obligatorii marcate | D | MAJOR | HTML corectat |
| act.webmcp | WebMCP | `find_dealer`, `get_model`, `book_test_drive` | P | INFO | snippet WebMCP |

## 6. Trust (10)
| ID | Ce verificăm | PASS | Met. | Sev. | Fix |
|---|---|---|---|---|---|
| trust.https | HTTPS | certificat valid, redirect HTTP → HTTPS | D | HIGH | — |
| trust.cookie_wall | Cookie wall | conținut accesibil fără interacțiune | D + V | MAJOR | — |
| trust.injection | Suprafață de injection | fără text ascuns cu instrucțiuni pentru agenți | D + L | MAJOR | — |
| trust.gdpr | GDPR pe formulare | text de consimțământ + link politică | D | MAJOR | text recomandat |
| trust.offer_validity | Oferte datate | perioadă de valabilitate + condiții în text și `validThrough` | D + L | MAJOR | JSON-LD |

## 7. Agent UX — Agent Journey (20)
Agent Muse Spark + Playwright, read-only, max 25 pași / 120 s.
| ID | Sarcina agentului | PASS | Met. | Sev. |
|---|---|---|---|---|
| ux.j_dealer | „Găsește cel mai apropiat dealer autorizat pentru modelul Y în {oraș}” | dealer corect + contact | J | CRITICAL |
| ux.j_price | „Care e prețul de la și garanția pentru modelul X?” | corect vs ground truth | J | HIGH |
| ux.j_compare | „Ce diferă între versiunile A și B?” | diferențe reale, din site | J | MAJOR |
| ux.j_act | „Deschide cererea de test drive și spune ce câmpuri cere” (fără submit) | formular găsit, câmpuri listate | J | HIGH |
| ux.blockers | Blocaje | 0 popup / CAPTCHA / 403 / conținut doar JS | J | MAJOR |
| ux.agent_vs_human | Agent vs om | ≥ 90% din informația vizibilă extrasă | J + V | MAJOR |

## 8. Protocol — AAP 3.0 aggregate + rețea (10)
Dacă `proto.aap_card` = fail → restul AAP = `na`; stratul = „not adopted” (0) + oportunitate.
| ID | Ce verificăm | PASS | Met. | Sev. | Ref AAP |
|---|---|---|---|---|---|
| proto.aap_card | Agent Card | `/.well-known/agent-card.json` valid; exact o extensie AAP `required: true` | P | CRITICAL | DISC-01/02 |
| proto.aap_version | Versiune | 3.0 pass · 1.x–2.x warn | P | MAJOR | DISC-03 |
| proto.consistency | Card ↔ poppy ↔ llms.txt | aceleași skill-uri, același MCP | P | MAJOR | DISC-06 |
| proto.mcp | Endpoint MCP din `params.mcp.url` | `server/discover` sau `initialize` OK | P | CRITICAL | MCP-01/02 |
| proto.tools | Tool-uri | `aap_*` din `tools/list` = skill-urile din card | P | CRITICAL | MCP-03 |
| proto.aap_aggregate | Scope aggregate | `dealer.information` + `inventory.search` cu `scope: aggregate` | P | HIGH | inventory-capabilities, exemple aggregate |
| proto.search | Căutare publică în rețea | `aap_inventory_search` anonim valid | P | HIGH | INV-01/02 |
| proto.onboarding | Fresh agent onboarding | domeniu → prima căutare < 60 s | P | MAJOR | ONB-01 |
| proto.network_adoption | Adopție AAP în rețea | % dealeri din locator cu `agent-card.json` | P | INFO | benchmark importator |
| proto.eu_profile | Profil AAP-EU | EUR/RON, TVA inclus, km/WLTP, GDPR | P | INFO | specificația AAP |
| proto.ucp | Manifest DMC-12 | `/.well-known/ucp` | P | INFO | strategie produs |

## 9. FAQ template
Garanție producător · intervale service · autonomie și încărcare EV · diferențe între versiuni · unde găsesc un dealer · finanțare marcă · termen de livrare · oferte curente.

## 10. Prompt panel (Visibility)
`cel mai bun SUV electric sub 50k €` · `{brand} {model} vs {competitor}` · `ce garanție are {brand}` · `dealer {brand} lângă {oraș}`

## 11. Siguranță
Nu trimitem formulare · nu apelăm tool-uri de scriere · URL-ul MCP vine doar din descoperire · probele pe site-urile dealerilor din rețea sunt doar GET pe `agent-card.json`.
