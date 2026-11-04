# AX Scanner

**Can an AI agent find, understand and act on your automotive website?** AX Scanner reads a site the way an agent would, scores how ready it is (0-100, grade A-F), shows exactly how it found each page, lets you replay the agent's attempt step by step, and drafts the fixes (JSON-LD, `llms.txt`, `robots.txt`) for you to approve.

> **Built with Meta Model API** (Muse Spark). See [How Muse Spark is used](#how-muse-spark-is-used) for exactly where, and what is not built yet.

Made for the Meta Global AI Developer Hackathon (Indie track).

## Why this matters: the step after the recommendation

Most of the conversation about AI and search is about **being seen**: does the assistant mention your brand, does it recommend your dealership. That is the first step. The step after it gets far less attention: once an assistant sends a buyer, or an agent goes to your site itself, can it **read the stock, trust the price, find the dealer, and book the test drive**? If the page hides its data behind JavaScript, an image or a form the agent cannot understand, the recommendation ends at a dead end.

AX Scanner measures that second step. It does not count mentions. It sends a Muse Spark agent to the site with a real task (find the nearest dealer, find a car under a budget), shows each move and the reason the model gave for it, checks every answer against the real page, and then drafts the fixes. Being recommended gets the agent to the door; AX Scanner checks whether the door opens.

## What it scans

Paste a domain. Step 0 classifies the site, then the matching rule set runs:

| Site type | Checks | What is specific |
|---|---|---|
| **Dealer** | 19 scored + 1 informative | stock pages (VDPs), vehicle and offer JSON-LD, price consistency, test drive, two agent journeys (find a car, find the booking form) |
| **Brand / importer** | 15 scored + 4 informative | model range, dealer locator readable in HTML, test-drive form, configurator / stock / shop detection, agent journey "find the nearest dealer" |
| **Online shop** | 17 scored + 1 informative | product JSON-LD and offers, add-to-cart and checkout *detected* (never executed), delivery / returns / warranty read and verified on the page, agent journey "find a product under a budget" |

Every type is scored over seven layers: **Discovery, Identity, Data, Actions, Trust, Agent UX, Protocol**. Weights come from `app/templates/*.yaml`. A failed CRITICAL check caps the grade at C. Checks that do not apply are excluded from the score. WebMCP tools (`toolname` attributes, `registerTool`) and AAP agent cards are detected.

## How a scan works

```
URL -> Step 0: classify (heuristics + Muse Spark) -> confirm if unsure
    -> discover pages: Muse reads the homepage links and picks each page (any language); keyword rules fill the gaps
       and a pick whose page does not look like its category is rejected
    -> read <= 15 pages (read-only GET, robots.txt respected, SSRF-safe)
    -> run the checks (deterministic code; Muse only reads policies and drives the agent journeys)
    -> score + report + fixes (dealers) for you to approve
```

What the report shows:

- **Score and layers**, top findings, every check with its evidence (pages, what is missing).
- **Discovery tab:** for each category (dealer network, test drive, stock, offers...) the page chosen, *who* found it (Muse, rules, both), Muse's reason, rejected or off-domain picks, and which checks used it.
- **Agent journey player:** replay the agent step by step: what it was shown (text, numbered links, forms), which link it chose and why, and the *same page without JavaScript* in an inert sandbox, so you can compare what a person sees with what an agent receives.
- **Fixes (dealers):** JSON-LD, `llms.txt`, `robots.txt` with the assumptions to verify and the gaps still yours to fill. Nothing is exportable until you approve it.
- **Leaderboard and history**, "Scan again", and a **partial report** when a site's `robots.txt` closes it to our scanner: a per-agent table of which AI agents the file allows or blocks (ChatGPT, Claude, Perplexity, Meta, Google...).

## How Muse Spark is used

| Capability | Where | State |
|---|---|---|
| Structured output (JSON schema) | site classification; link-role and page picking; policy reading; every agent step | **in use** |
| Agent loop | the journeys (`ux.j_*`): Muse decides open-link / go-to / back / finish on a read-only, no-JavaScript browser; the answer is then **verified against the page** (price, VIN, dealer phone... must exist there) | **in use** (structured actions, not function calling) |
| Vision (price inside an image) | `*.price_readable` | not built; the check reports `vision: deferred` |
| Search grounding (Visibility score) | would measure whether assistants recommend the site | feasibility verified (`/responses` + `web_search`), **not built**; the score is readiness only |

Muse calls are cached per link list, retried once on timeouts / 429 / 5xx, and any model answer that points outside the data it was given (an index not in the list, a quote not on the page) is discarded.

## Quick start

Requirements: Python 3.12+, Node 20+ (only to build the UI).

```bash
pip install -r requirements.txt
cp .env.example .env            # set META_API_KEY
cd web && npm ci && npm run build && cd ..
uvicorn app.main:app --port 8000   # UI + API on http://localhost:8000
```

Without `META_API_KEY` the server starts but refuses scans with a clear message (the UI shows a banner).

UI development: `cd web && npm run dev` (port 5173, proxies `/api` to 8000).

### Configuration (`.env`)

| Variable | Default | Meaning |
|---|---|---|
| `META_API_KEY` | - | required for scans |
| `META_API_BASE` / `META_MODEL` | `https://api.meta.ai/v1` / `muse-spark-1.3` | Meta Model API |
| `DATABASE_URL` | `sqlite:///./ax.db` | SQLite file or a Postgres URL |
| `MAX_SCANS_PER_DAY` | `0` (no cap) | cap on new scans per rolling 24 h for a public deploy |
| `ALLOW_IGNORE_ROBOTS` | `true` | the opt-in "scan ignoring robots.txt"; set `false` on a public deployment |

More knobs (timeouts, retries, journey steps and budget) are in `app/config.py`.

### Tests

```bash
pytest -q                                  # 272 tests, no network, no key needed
RUN_LIVE_LLM=1 pytest tests/test_demo_site.py   # 2 opt-in tests that call the real Muse agent
```

### Docker / deploy

`Dockerfile` builds the UI and the API into one image (about 270 MB, Playwright excluded). `railway.json` is ready: mount a volume at `/data` (`DATABASE_URL=sqlite:////data/ax.db`), set `META_API_KEY`, `ALLOW_IGNORE_ROBOTS=false` and `MAX_SCANS_PER_DAY`, run **a single replica** (the rate limiter and scan tasks are in-process). Health check: `/health`. Step by step, with seeding the leaderboard: [docs/DEPLOY.md](docs/DEPLOY.md).

## A site that scores 100

`demo/sample-brand-site/` is a tiny fictional car brand in plain HTML plus a small script. Its dealer network is in the HTML, it declares an AAP agent card, and the real Muse agent finds a dealer on it and passes `ux.j_dealer`. The same page with the list filled in by JavaScript only makes the agent fail. Run it:

```bash
python -m tests.demo_site_runner              # real agent (needs META_API_KEY)
python -m tests.demo_site_runner --js-only    # the control that should fail
python -m http.server 8080 --directory demo/sample-brand-site   # just to look at it
```

The agent card's endpoints are placeholders (no live MCP server); see `demo/sample-brand-site/README.md`.

## API

| Endpoint | |
|---|---|
| `POST /api/scans` | `{url, force?, ignore_robots?}`; refuses with 503 without a key |
| `GET /api/scans`, `GET /api/scans/{id}` | history, scan with report |
| `POST /api/scans/{id}/confirm` | choose the site type when Step 0 is unsure |
| `GET /api/scans/{id}/page?url=` | a page the scan recorded, as an inert no-JavaScript view |
| `GET /api/scans/{id}/fixes`, `POST /api/fixes/{id}/approve` / `reject`, `GET /api/scans/{id}/export` | fixes; export contains approved fixes only |
| `GET /api/leaderboard` | latest completed scan per domain, outdated rules flagged |
| `GET /health` | status, whether a key is configured |

## Responsible scanning

- **Read-only.** Only GET requests; forms are inspected, never submitted; carts and checkouts are detected, never used; no logins.
- **robots.txt is respected.** If it closes the site to the scanner you get a partial report, not a crawl. The "ignore robots.txt" option is opt-in, needs a confirmation that you own the site or may scan it, is stated in the report, and can be switched off on the server.
- **SSRF-safe fetching** (public hosts only, every redirect validated), a polite pace, at most 15 pages per scan, rate limiting.
- **Site text is untrusted.** The agent is told so, picks are made by index among links the crawler saw, and the verifier checks claims against the real page. Third-party pages shown in the report are stripped of scripts and served under `CSP: sandbox` inside an iframe with an empty `sandbox` attribute.

## Limits (honest list)

- The agent browses **without JavaScript**. On sites that load the dealer list or stock by script it fails, which is a real finding for crawlers but not for browser agents. Of the 12 real brand sites scanned, 1 (dacia.ro) passes `ux.j_dealer` in its latest scan, and it failed on earlier runs of the same site; the clean positive case is the demo site. Of 11 real dealers, 5 pass `ux.j_find`.
- Scores move a few points between runs (journeys and page picking involve a model). A repeat test on four sites gave a spread of 0 to 5.8 points. Reports carry a `scoring_version`; the leaderboard marks scans made with older rules.
- Some sites block the scanner (WAF 403 / robots.txt): autodoc.es, automobilus.ro, peugeot.fr, outletcars.es.
- Fixes exist for dealers only. Visibility, the free/paid paywall, Agent Card fix and vision are not built.
- Schema.org validation of fixes is structural, not the official validator.
- UI is English only.

## Repository map

| Path | |
|---|---|
| `app/` | FastAPI backend: `api/`, `checks/` (one module per layer family and site type), `journey/` (agent loop, no-JS browser, verifiers), `fixes/`, `services/` (crawler, classifier, link resolver, discovery view), `domain/` (scoring, classification), `templates/` (rule sets as YAML) |
| `web/` | React + Vite + TypeScript + Tailwind v4 UI (shadcn-style components) |
| `demo/sample-brand-site/` | the demo site |
| `docs/` | `MVP-PLAN.md`, `UI-PLAN.md`, `GAP-ANALYSIS.md`, check specs in `docs/checks/` |
| `aap-v3.0-spec/` | not included. Optional, only for the AAP schema test and `scripts/aapval.py`: clone [auto-agent-protocol](https://github.com/auto-agent-protocol/auto-agent-protocol) into this folder |
| `tests/`, `scripts/`, `data/` | tests; CLI tools (`scan_url.py`, `rescan_outdated.py`, `run_baseline.py`); the 50-domain classification set |

## License

MIT. See [LICENSE](LICENSE).
