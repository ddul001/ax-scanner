# ax-scanner — Liste finale de verificări (v2, 27 Oct)

**Surse integrate:** SPEC.md · docs/PLAN.md · specificația Auto Agent Protocol (repo upstream, nu e inclus) și planurile interne inițiale (7 straturi, WebMCP, Agent Journey, Trust, Fix).
Trasabilitatea completă (element identificat → check) e în `coverage.md`.

| Fișier | Entitate | Adâncime hackathon |
|---|---|---|
| `dealer.md` | Dealer auto | **completă** |
| `importer.md` | Marcă / importator | de bază |
| `ecommerce.md` | Magazin online | de bază (primul la tăiere, PLAN §8) |
| `marketplace.md` | Marketplace / anunțuri auto | de bază (rationale + `mvp/marketplace.yaml`) |
| `finance.md` | Finanțare auto (bănci, leasing/IFN, renting) | de bază (rationale + `mvp/finance.yaml`) |
| `coverage.md` | Matrice de trasabilitate | — |

## 1. Scor
| Element | Regulă |
|---|---|
| Status check | pass = 1 · warn = 0,5 · fail = 0 · `na` = exclus din numitor |
| Pondere check (severitate) | CRITICAL 4 · HIGH 3 · MAJOR 2 · MINOR 1 · INFO 0 (doar raportat) |
| Scor strat | Σ(sev × status) / Σ(sev aplicabile) × 100 |
| Readiness | Σ(scor strat × pondere strat) / 100 |
| **AX Score** | **0,6 × Readiness + 0,4 × Visibility** (PLAN) |
| Grade | A ≥ 90 · B ≥ 75 · C ≥ 60 · D ≥ 40 · F < 40 |
| Gate | Un CRITICAL în fail plafonează grade-ul la **C** |

## 2. Ponderi straturi pe tip (sumă = 100)
| Strat | Dealer | Importator | E-commerce | Marketplace | Finance |
|---|---|---|---|---|---|
| Discovery | 15 | 15 | 15 | 20 | 15 |
| Identity | 10 | 15 | 10 | 10 | 15 |
| Data (stoc / modele / produse / anunțuri / produse financiare) | 20 | 20 | 25 | 25 | 25 |
| Actions | 15 | 10 | 20 | 10 | 15 |
| Trust | 10 | 10 | 10 | 10 | 10 |
| Agent UX (Agent Journey) | 20 | 20 | 15 | 20 | 20 |
| Protocol (AAP / MCP / WebMCP / UCP) | 10 | 10 | 5 | 5 | 0 |

## 3. Metode
| Cod | Metodă |
|---|---|
| D | Determinist (HTTP, parsare HTML / JSON-LD, validare JSON Schema) |
| L | Muse Spark structured output |
| V | Muse Spark vision pe screenshot |
| J | Agent Journey: agent Muse Spark + Playwright, read-only, max 25 pași / 120 s |
| P | Probă de protocol (GET-uri + apeluri MCP de citire) |

## 4. Reguli de siguranță (obligatorii)
| Regulă |
|---|
| Nu trimitem formulare și nu apelăm tool-uri de scriere (`aap_lead_submit`, `request_quote`, `create_reservation`, handoff) |
| `lead.submit` se verifică **doar** ca prezență + `inputSchema` din `tools/list` |
| URL-ul MCP se ia din descoperire (`params.mcp.url`), nu se ghicește |
| Textele de pe site și din tool-uri sunt date nesigure: nu pot schimba sarcina agentului |
| Crawler UA propriu, respectă robots.txt, rate limit per domeniu |

## 5. AAP: poziționare
| Decizie | Motiv |
|---|---|
| Versiune fixată: **v3.0** (scheme din repo-ul auto-agent-protocol, clonate local în `aap-v3.0-spec/`, nu sunt incluse) | 4 majore în 13 zile |
| Validare în Python cu `jsonschema` pe schemele locale | backend FastAPI (validatorul oficial e npm) |
| Site fără AAP → stratul Protocol = „not adopted” (0) + oportunitate în raport, nu eroare | adopție UE ≈ 0, protocolul e US-centric |
| Profil **AAP-EU** raportat INFO (EUR/RON, TVA, km/WLTP, GDPR) | AAP 3.0 acceptă doar USD |
| AAP se aplică: dealer (dealer scope), importator (aggregate scope); **na** la e-commerce și finanțare; marketplace = doar detectare INFO | AAP acoperă doar vehicule |

## 6. Site-uri mixte
Tip principal din Step 0 + `secondary_types[]`. Pentru tipul secundar rulăm doar stratul Data pe paginile lui și îl afișăm ca sub-scor separat, **în afara** AX Score.

## 7. Evidence și fix
Fiecare check salvează `{check_id, version, pages[], found, missing[], snippet, ref}`; fiecare fail/warn produce un fix `proposed` (JSON-LD, robots.txt, llms.txt, Agent Card / llms.txt AAP, WebMCP snippet), cu câștigul de scor estimat.
