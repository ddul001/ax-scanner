# Marketplace auto — rationale (hackathon: de bază)

**Tip:** platforme de anunțuri / agregatoare auto cu mulți vânzători independenți (autovit.ro, autoscout24.es, coches.net). **YAML:** `mvp/marketplace.yaml` (18 check-uri MVP, 31 amânate). Scor, metode, siguranță: `README.md` și `mvp/_scoring.yaml`.

## 1. Ce are nevoie un agent AI de la un marketplace
Cumpărătorul îi cere agentului „găsește un diesel sub 15.000 €, sub 100.000 km, în Cluj”. Agentul trebuie să (1) fie lăsat să intre, (2) construiască o căutare filtrată prin URL, (3) parcurgă rezultatele pe pagini, (4) citească din anunț prețul, km, anul, vânzătorul, (5) știe dacă anunțul mai e valabil, (6) vadă cum se contactează vânzătorul. Marketplace-urile sunt cele mai agresive în blocarea boților (anti-scraping), deci **blocarea agenților este constatarea principală** a raportului.

## 2. Ponderi
| Strat | Pondere | Motiv |
|---|---|---|
| Discovery | 20 | Mai mare decât la dealer (15): WAF/robots decid dacă agentul intră deloc; aici intră și căutarea filtrată prin URL (`lst.search_urls`) |
| Identity | 10 | Identitatea contează la nivel de **vânzător** (privat vs profesionist), nu de site |
| Data | 25 | Miezul produsului: anunțuri, paginare, câmpuri, preț, prospețime |
| Actions | 10 | Doar contactul fără login; marketplace-urile își protejează intenționat canalul de contact |
| Trust | 10 | Anti-fraudă și termeni de acces automat |
| Agent UX | 20 | Agent Journey pe căutare filtrată |
| Protocol | 5 | AAP nu se aplică (vezi mai jos); rămâne doar detectare INFO |

## 3. De ce există fiecare check
- **disc.robots_ai, disc.waf_ua** (CRITICAL pe WAF): fără acces nu există nimic altceva. Aceeași implementare ca la celelalte tipuri.
- **disc.sitemap, disc.no_js**: agentul descoperă anunțuri din sitemap; lista de rezultate și prețul trebuie să fie în HTML brut.
- **lst.search_urls** (CRITICAL): filtrele ca parametri GET sunt singura cale ca agentul să reproducă o căutare fără UI.
- **lst.listing_urls** (CRITICAL), **lst.pagination**: agentul trebuie să poată merge de la rezultate la anunț și la pagina următoare.
- **lst.schema, lst.fields**: Vehicle + Offer pe anunț, ItemList pe rezultate; câmpurile minime (preț, monedă, km, an, VIN sau ID anunț).
- **lst.price_readable** (CRITICAL, D+V): prețul ca text; vision doar pe eșantion când textul lipsește.
- **lst.freshness**: un anunț vândut care răspunde 200 induce agentul în eroare; așteptat 404/410 sau `SoldOut`.
- **id.seller_type**: persoană fizică vs profesionist schimbă garanția și drepturile consumatorului.
- **act.contact_no_login**: doar verificăm că există și dacă e gated; nu trimitem nimic.
- **trust.scam_signals, trust.automation_terms**: semnale anti-fraudă și regula de acces automat (clauze „no scraping” = risc juridic pentru agent).
- **ux.j_find** (CRITICAL): jurnal read-only, aceeași sarcină pe toate site-urile pentru comparabilitate.

## 4. AAP
AAP 3.0 vizează dealer scope și importator (aggregate scope pe domeniul mărcii). Marketplace-ul nu este un dealer și nu publică un contract AAP al unui terț, deci **nu se validează**: `proto.aap_detect` este **doar detectare, severitate INFO** (agent card / MCP public prezent da/nu), fără impact pe scor. Dacă un marketplace ar adopta AAP aggregate, se tratează în V2 (`proto.aap_aggregate`).

## 5. Amânat în V2
`disc.llms_txt` (valoare mică pe marketplace, de adăugat ușor, aceeași implementare), `lst.price_consistency`, `lst.price_final`, `lst.dedupe`, `lst.sort_urls`, feed/API, `lst.schema_seller`, `lst.price_rating`, `trust.gdpr`, `trust.seller_history`, `ux.j_contact`, `ux.j_compare`, `proto.mcp`. Motiv: cer mai multe pagini sau judecăți subiective, fără câștig clar pentru demo.
