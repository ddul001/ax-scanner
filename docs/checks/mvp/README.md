# Checks MVP (hackathon META)

Subset implementat din catalogul complet `../dealer.md`, `../importer.md`, `../ecommerce.md`, `../marketplace.md`, `../finance.md` (rămân sursa de adevăr, V2).

| Fișier | Check-uri MVP | Amânate (V2) |
|---|---|---|
| `_scoring.yaml` | reguli comune de scor + siguranță | — |
| `dealer.yaml` | 19 | 35 |
| `importer.yaml` | 17 | 30 (+ % rețea AAP) |
| `ecommerce.yaml` | 17 | 23 (+ AAP `na`) |
| `marketplace.yaml` | 18 | 31 (AAP doar detectare INFO) |
| `finance.yaml` | 18 | 27 (+ AAP `na`, protocol 0) |

**Reguli**
- Un singur motor: `id` + `layer` + `method` + `severity`; fără clase per tip.
- Straturile fără check-uri aplicabile se renormalizează.
- Protocol = doar detectare (AAP card / MCP-UCP-ACP), fără validare de protocol.
- Muse Spark doar pe: `*.price_readable` (vision), `trust.policies_text` (structured), Agent Journey (`ux.j_*`).

**Ordine de tăiere dacă întârzii:** protocol → ux.j_act → trust → ecommerce întreg.
