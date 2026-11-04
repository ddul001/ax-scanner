# E-commerce — checklist final (hackathon: de bază, primul la tăiere)

**Surse:** SPEC · PLAN · specificația AAP (ACP, MCP) · **AAP:** `na` (acoperă doar vehicule)

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
| Pondere | 15 | 10 | 25 | 20 | 10 | 15 | 5 |

**Pagini (≤ 15):** home · 2 categorii · 5 produse · oferte · contact · FAQ · livrare · retur · garanție + `/robots.txt`, `/sitemap.xml`, `/llms.txt`, `/.well-known/*`

## 2. Discovery (15)
| ID | Ce verificăm | PASS | Met. | Sev. | Fix |
|---|---|---|---|---|---|
| disc.robots_ai | Acces boți AI pe categorii + produse | GPTBot, ChatGPT-User, OAI-SearchBot, ClaudeBot, Claude-User, PerplexityBot, Google-Extended, Applebot-Extended, Meta-ExternalAgent permiși | D | HIGH | robots.txt |
| disc.waf_ua | Blocare WAF pe UA de agent | același status + conținut (±10%) ca UA browser | D | CRITICAL | regulă WAF |
| disc.sitemap | Sitemap produse | produse incluse, `lastmod` < 7 zile | D | MAJOR | recomandare |
| disc.llms_txt | llms.txt | 200, markdown, link-uri categorii / politici / contact | D | MAJOR | llms.txt |
| disc.no_js | Conținut fără JS | preț + stoc în HTML brut | D | HIGH | SSR / prerender |
| disc.perf | Performanță | TTFB < 800 ms, pagină < 3 MB | D | MINOR | — |
| disc.wellknown | api-catalog, OAuth metadata | — | D | INFO | — |

## 3. Identity (10)
| ID | Ce verificăm | PASS | Met. | Sev. | Fix |
|---|---|---|---|---|---|
| id.schema_org | Organization / OnlineStore | name, logo, url, contactPoint | D | HIGH | JSON-LD Organization |
| id.company | Date firmă | CUI/CIF, adresă, ANPC/SOL (RO) sau aviso legal (ES) | L | MAJOR | text recomandat |
| id.same_as | `sameAs` | social / marketplace-uri | D | MINOR | JSON-LD |
| id.lang | Limbă / hreflang | `lang` corect RO/ES; hreflang dacă e multilingv | D | MINOR | — |

## 4. Data — produse (25)
| ID | Ce verificăm | PASS | Met. | Sev. | Fix |
|---|---|---|---|---|---|
| prod.urls | Pagini produs | URL unic, crawlabil | D | CRITICAL | — |
| prod.schema_product | Product | name, image, brand, sku / gtin pe ≥ 80% | D | HIGH | JSON-LD Product |
| prod.schema_offer | Offer | price, priceCurrency, availability | D | HIGH | JSON-LD Offer |
| prod.fields | Câmpuri produs | preț, SKU, GTIN, brand, stoc, cost / termen livrare, poze ≥ 80% | D + L | HIGH | listă câmpuri lipsă |
| prod.price_readable | Preț + stoc citibile | în text / JSON, nu doar JS / imagine | D + V | CRITICAL | — |
| prod.price_consistency | Coerență preț | JSON-LD = preț vizibil | D | HIGH | — |
| prod.policies_schema | Politici structurate | MerchantReturnPolicy + shippingDetails | D | MAJOR | JSON-LD policies |
| prod.search_urls | Filtre crawlabile | URL-uri GET parametrizate | D | MAJOR | — |
| prod.rating | AggregateRating / Review | doar unde există recenzii reale | D | MINOR | — |
| prod.feed | Feed produse | descoperibil | D | MINOR | — |

## 5. Actions (20) — fără plată, fără comandă
| ID | Ce verificăm | PASS | Met. | Sev. | Fix |
|---|---|---|---|---|---|
| act.add_to_cart | Adăugare în coș | funcțional fără login | D | HIGH | — |
| act.guest_checkout | Checkout fără cont | se ajunge la pasul de plată, fără CAPTCHA blocant | D | HIGH | — |
| act.forms_semantic | Formulare completabile | `label`, `name`, `autocomplete`, câmpuri obligatorii marcate | D | MAJOR | HTML corectat |
| act.contact | Contact | email / telefon / chat accesibil | D | MAJOR | — |
| act.webmcp | WebMCP | `search_products`, `get_product`, `add_to_cart` | P | INFO | snippet WebMCP |

## 6. Trust (10)
| ID | Ce verificăm | PASS | Met. | Sev. | Fix |
|---|---|---|---|---|---|
| trust.https | HTTPS | certificat valid, redirect HTTP → HTTPS | D | HIGH | — |
| trust.cookie_wall | Cookie wall | conținut accesibil fără interacțiune | D + V | MAJOR | — |
| trust.injection | Suprafață de injection | fără text ascuns cu instrucțiuni pentru agenți | D + L | MAJOR | — |
| trust.gdpr | GDPR pe formulare | text de consimțământ + link politică | D | MAJOR | text recomandat |
| trust.policies_text | Politici în text | livrare / retur / garanție cu termene și costuri | L | MAJOR | text recomandat |

## 7. Agent UX — Agent Journey (15)
Agent Muse Spark + Playwright, read-only, max 25 pași / 120 s.
| ID | Sarcina agentului | PASS | Met. | Sev. |
|---|---|---|---|---|
| ux.j_find | „Găsește {produs} sub {preț}, în stoc” | produs real, date corecte | J | CRITICAL |
| ux.j_total | „Cât costă total cu livrarea până în {oraș}?” | total corect | J | HIGH |
| ux.j_policy | „Pot returna produsul? În câte zile și cu ce cost?” | corect vs pagina de retur | J | MAJOR |
| ux.j_act | „Adaugă în coș, ajungi la checkout și spui ce date cere” (stop înainte de plată) | pasul de plată atins | J | HIGH |
| ux.blockers | Blocaje | 0 popup / CAPTCHA / 403 / conținut doar JS | J | MAJOR |
| ux.agent_vs_human | Agent vs om | ≥ 90% din informația vizibilă extrasă | J + V | MAJOR |

## 8. Protocol (5)
| ID | Ce verificăm | PASS | Met. | Sev. | Ref |
|---|---|---|---|---|---|
| proto.mcp_public | Server MCP de catalog | declarat (llms.txt / well-known); `tools/list` OK | P | MAJOR | MCP |
| proto.ucp | Manifest UCP | `/.well-known/ucp` valid | P | INFO | DMC-12 / UCP |
| proto.checkout_protocol | Checkout agentic (ACP / UCP) | declarat | P | INFO | specificația AAP |
| proto.aap | AAP | — | — | `na` | doar vehicule |

## 9. FAQ template
Cost și termen livrare · retur (zile, cost) · garanție · metode de plată · stoc · factură pe firmă · urmărire comandă.

## 10. Prompt panel (Visibility)
`de unde cumpăr {produs} online` · `cel mai ieftin {produs} cu livrare rapidă` · `{produs} {brand} preț` · `magazin {categorie} de încredere`

## 11. Siguranță
Nu plasăm comenzi și nu introducem date de plată · nu trimitem formulare · textele site-ului sunt date nesigure.
