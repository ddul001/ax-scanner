# Finanțare auto (bănci, leasing/IFN, renting) — rationale (hackathon: de bază)

**Tip:** instituții financiare relevante pentru cumpărătorii de mașini: bănci (secțiune credit auto), IFN-uri de leasing, creditori de consum, ramuri captive, firme de renting cu catalog. **YAML:** `mvp/finance.yaml` (18 check-uri MVP, 27 amânate). Scor, metode, siguranță: `README.md` și `mvp/_scoring.yaml`.

## 1. Ce are nevoie un agent AI de la un site financiar
Întrebarea tipică: „cât e rata, DAE și avansul pentru o mașină de 25.000 € pe 48 de luni?”. Agentul trebuie să (1) intre pe site, (2) găsească produsul potrivit (leasing, renting, credit), (3) citească costul **ca text**: dobândă, DAE/TAE, durată, avans, valoare reziduală, rată, (4) folosească sau măcar descrie calculatorul, (5) confirme că instituția este reglementată (BNR / Banco de España), (6) știe cum se solicită oferta și ce consimțământ se cere. Costul neclar sau ascuns în imagini face agentul să halucineze cifre: risc real pentru utilizator.

## 2. Ponderi
| Strat | Pondere | Motiv |
|---|---|---|
| Discovery | 15 | Ca la dealer |
| Identity | 15 | Mai mare (dealer 10): identitatea legală și înregistrarea la BNR/Banco de España sunt condiție de încredere |
| Data | 25 | Nu există stoc; datele sunt produsele și **transparența costului** (ca la e-commerce) |
| Actions | 15 | Calculatorul/simulatorul este acțiunea principală; formularul de ofertă doar analizat |
| Trust | 10 | HTTPS și consimțământ GDPR |
| Agent UX | 20 | Jurnal pe cost și pe calculator |
| Protocol | 0 | `na`: AAP acoperă doar vehicule/dealeri, nu produse financiare; MCP/UCP rămân în V2 |

## 3. De ce există fiecare check
- **disc.* (5)**: aceleași implementări ca la celelalte tipuri; `disc.no_js` verifică dobânda/DAE/rata în HTML brut (calculatoarele sunt adesea JS-only).
- **id.schema_org**: Organization/BankOrCreditUnion/FinancialService; FAQPage ca bonus (răspunsuri citabile de agent).
- **id.regulatory** (L): denumire legală, CUI, nr. Registrul BNR sau Banco de España, sediu; verificăm doar textul din footer/pagini legale.
- **id.contact**: ≥ 2 canale; agentul poate trimite utilizatorul mai departe.
- **fin.product_urls** (CRITICAL): fără URL per produs nu există ce citi.
- **fin.cost_text** (CRITICAL, D+V): rata sau dobânda + DAE ca text; imaginile/bannerele nu contează.
- **fin.terms_fields**: durată, avans, valoare reziduală, comisioane, monedă, eligibilitate.
- **fin.schema_product**: FinancialProduct/LoanOrCredit/Offer; schema.org le are, dar adopția e mică, deci prag de 50%.
- **act.calculator**: câmpuri etichetate și parametrizabile prin GET sau form semantic; **nu se trimite niciodată**.
- **act.forms_semantic, trust.gdpr_consent**: analizăm doar etichetele și textul de consimțământ, fără submit.
- **ux.j_cost** (CRITICAL), **ux.j_calc**: Agent Journey read-only.

## 4. AAP
`na`: AAP 3.0 definește dealer scope și aggregate scope pentru vehicule; o instituție financiară nu are inventar. Nu se face nici detectare; stratul Protocol are pondere 0 și nu intră în scor. Un renting cu catalog de vehicule poate fi scanat și ca secundar (dealer/importator) conform README §6.

## 5. Amânat în V2
`fin.rep_example` (exemplu reprezentativ legal), `fin.price_consistency` (JSON-LD = text), `fin.fees_total_cost`, `fin.catalogue_vehicles` (catalog renting), `fin.rate_freshness`, `fin.eligibility_machine`, `fin.feed`, `trust.risk_warning`, `trust.complaints_odr`, `ux.j_compare`, `ux.j_eligibility`, `proto.mcp_public`. Motiv: cer interpretare juridică fină sau mai multe pagini; se adaugă după validarea pe site-uri reale.
