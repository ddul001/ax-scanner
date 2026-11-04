# Fixtures — scor maxim

| Fișier | Tip | Checklist |
|---|---|---|
| `dealer-max.html` | Dealer (AutoNova Cluj, marcă fictivă Velora) | `docs/checks/dealer.md` |
| `importer-max.html` | Importator (Velora România) | `docs/checks/importer.md` |
| `ecommerce-max.html` | E-commerce (PieseNova) | `docs/checks/ecommerce.md` |

- Toate entitățile, domeniile (`*.example`), VIN-urile și CUI-urile sunt fictive.
- `data-check="..."` marchează ce check acoperă fiecare element.
- `<script data-sim-path="...">` simulează endpoint-uri: `/robots.txt`, `/sitemap.xml`, `/llms.txt`, `/.well-known/agent-card.json`, `/.well-known/poppy.json`, `/.well-known/ucp`, răspunsuri MCP (`mcp:*`). Serverul de test le servește la acel path.
- Check-urile de rețea (`disc.waf_ua`, `disc.perf`, `trust.https`) și Agent Journey depind de serverul de test: servește pagina pe HTTPS, la fel pentru orice UA.

## Verificare scor (27 Oct 2026)
Rulare: `python scripts/score_fixtures.py` (necesită `jsonschema>=4.18`, `openssl`). Rapoarte: `fixtures/reports/<tip>.json`.

| Fixture | AX Score | Readiness | Visibility (simulat) | Grade | pass / fail / na |
|---|---|---|---|---|---|
| dealer-max.html | **100,0** | 100,0 | 100,0 (4 prompturi × 3) | A | 54 / 0 / 0 |
| importer-max.html | **100,0** | 100,0 | 100,0 (4 prompturi × 3) | A | 47 / 0 / 0 |
| ecommerce-max.html | **100,0** | 100,0 | 100,0 (4 prompturi × 3) | A | 40 / 0 / 1 (`proto.aap` na) |

**Test negativ:** o copie a paginii dealer cu 5 defecte (GPTBot blocat, preț în imagine, câmp fără autocomplete, TVA neinclus, cookie overlay) scoate 69,8 / C, cu 10 check-uri picate. Asta confirmă că check-urile chiar diferențiază paginile, nu trec automat.

| Componentă | Cum e verificată |
|---|---|
| HTTPS, viteză, blocare pe user-agent | Server de test real (`scripts/testserver.py`): TLS cu certificat local, 9 user-agenți de boți AI comparați cu browserul |
| AAP 3.0 | Agent Card, poppy, căutare, detaliu vehicul, eroare și dealer.information validate pe schemele oficiale (`scripts/aapval.py`, necesită clona locală `aap-v3.0-spec/`); MCP JSON-RPC real: `initialize`, `server/discover`, `tools/list`, `tools/call` |
| `lead.submit` | Doar `inputSchema`; tool-ul nu e apelat niciodată |
| Agent Journey | Agent **scriptat determinist** (navigare + extragere + comparare cu ground truth), fără LLM. Rularea cu Muse Spark vine în D3–D5 |
| Visibility (40% din AX) | Răspunsuri grounded **simulate** în `visibility:panel` (menționat 0,5 + 1/rank × 0,3 + citat 0,2) |

Endpoint-urile AAP simulate sunt generate din exemplele oficiale v3.0 cu `scripts/build_sims.py`.
