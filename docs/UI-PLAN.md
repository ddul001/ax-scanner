# AX Scanner - UI (as built) and remaining work

**Updated:** 2026-11-02 · **Deadline:** 4 Nov 20:00 (Bucharest) · Independent design system for this project. English only.

## 1. Decisions (taken)
| Topic | Decision |
|---|---|
| Stack | **React 19 + Vite + TypeScript + Tailwind v4**, components written in the shadcn/ui style on Radix primitives (button, card, badge, tabs, progress, collapsible, input). `lucide-react` icons, `react-router-dom` |
| Serving | `npm run build` -> `web/dist`; FastAPI serves it with an SPA fallback (`app/main.py`). One deploy, no CORS. Dev: `npm run dev` (:5173) proxies `/api` to :8000. A rebuilt `dist` is picked up without restarting the server |
| Language | English only. No i18n layer |
| Visual direction | Sober "audit instrument": cool neutrals, one blue accent, status = colour + icon + text. Light and dark, toggle saved in `localStorage` (try/catch) |
| Product name | AX Scanner, score = "AX Score" |
| Paywall | Not built (cut candidate) |
| Visibility tab | **Removed.** The "Not active" placeholder was replaced by the Discovery tab; Visibility is postponed |

## 2. Principles
1. The score leads to action: every finding has an impact, fixes are reviewed and approved before export ("no export without approval").
2. Honesty: what is not built is not shown as if it were; gains are labelled "estimated"; figures come from the scan; assumptions and gaps of a fix are shown next to it.
3. Read-only is visible: home and footer state that the scanner never submits forms; the report says when robots.txt was ignored by request.
4. One primary action per screen.
5. Text from scanned sites is rendered only through React text nodes (no `dangerouslySetInnerHTML`, no `innerHTML`). The one place that shows a third party's page (the agent player) uses an iframe with an empty `sandbox` attribute and a server-side CSP `sandbox`.

## 3. Design tokens (`web/src/index.css`)
| Token | Light | Dark | Role |
|---|---|---|---|
| background | `#F7F8FA` | `#0E1116` | page |
| card | `#FFFFFF` | `#161B22` | panels |
| muted | `#EEF0F4` | `#1E252E` | code blocks, bar tracks |
| foreground / muted-foreground | `#0F172A` / `#5B6575` | `#E6EAF0` / `#9AA6B5` | text |
| border | `#DDE1E8` | `#2A323D` | 1px lines |
| primary | `#2F5BFF` | `#6C8CFF` | CTA, links, current item |
| ok / warn / fail | `#12805C` / `#B26A00` / `#C23B3B` | `#3DD598` / `#F2B84B` / `#FF7A7A` | PASS / WARN / FAIL |

Fonts: Inter (UI) and JetBrains Mono (check IDs, code, URLs) from Google Fonts, `display=swap`. Radius 6px (controls) / 10px (cards). Shadow only a 1px hairline on cards. `prefers-reduced-motion` disables transitions. `:focus-visible` ring uses the primary colour.

Status vocabulary (never colour alone): Pass (check icon, green), Warn (dot icon, amber), Fail (x icon, red), N/A (dashed badge, grey). Severity: CRITICAL, HIGH, MAJOR, MINOR as outlined badges. Fix status: proposed (primary outline), approved (green), rejected (grey). Discovery source: "Found by LLM" (primary), "LLM + rules agree" (green), "Found by rules" (grey), "Not found" (dashed).

## 4. Pages and components (built)
| Route | File | What it does | API |
|---|---|---|---|
| `/` | `pages/Home.tsx` | headline and URL form (missing-key banner, opt-in "ignore robots.txt" checkbox hidden when the server disables it, read-only / robots.txt note), "How a scan works" in 4 steps (classify, discover, check and try, report), the three site types, what the report contains (score and layers, discovery map, agent replay, fixes), and the top 5 of the leaderboard when there are at least 3 scans | `POST /api/scans`, `GET /health`, `GET /api/leaderboard` |
| `/scan/:id` | `pages/ScanPage.tsx` | Polls every 2 s. States: progress stepper, type confirmation, failed (typed errors), **partial report** (robots.txt closes the site to the scanner), full report | `GET /api/scans/{id}`, `POST .../confirm` |
| `/scan/:id` (partial) | `components/PartialReport.tsx` | verdict on AI-agent access, two tables (user-facing agents, training crawlers) with allowed / blocked, and a "Scan it anyway" card with a permission checkbox | same |
| `/scan/:id` (report) | `pages/ScanPage.tsx`, `components/report.tsx` | score card, layer bars with weights, scan details (including "Analysed with: Meta Model API: <model> (what ran)"), "robots.txt was ignored" banner, top 3 findings, tabs below; "Review fixes (n)" only when there are fixes | same |
| tab **Checks** | `components/report.tsx` | filter by layer / status, expandable evidence | |
| tab **Agent journey** | `components/AgentPlayer.tsx` | task header with the verifier's checks, step chips with previous / next, **"What the agent saw"** (text, numbered links with the chosen one highlighted, forms), **"The same page without JavaScript"** (iframe shown by default, hide toggle), "Then the agent..." with its reason, final answer at the last step. Falls back to a plain timeline for scans made before views were stored | `GET /api/scans/{id}/page?url=` |
| tab **Discovery** | `components/DiscoveryView.tsx` | summary numbers, one row per category (page, who found it, Muse's reason, rejected / other-domain picks, HTTP status, checks that used it), item pages (models / products / vehicles), all pages opened | none (report data) |
| `/scan/:id/fixes` | `pages/FixesPage.tsx` | fix cards (type, status, target URL, estimated gain, "Please verify", "You still need to add", code with Copy), Approve / Reject, export approved with per-file download | `GET .../fixes`, `POST /api/fixes/{id}/approve` / `reject`, `GET .../export` |
| `/history` | `pages/HistoryPage.tsx` | all scans with filters, 5 s refresh, "Partial (robots.txt)" label | `GET /api/scans` |
| `/leaderboard` | `pages/LeaderboardPage.tsx` | latest completed scan per domain, rank, type, AX + grade, weakest layer, "outdated" badge for scans made with older rules | `GET /api/leaderboard` |

Shared: `components/Layout.tsx` (sticky header: Scan, History, Leaderboard, theme toggle; read-only footer), `components/ui/*`, `lib/api.ts` (typed client, `ApiError`, `isPartial`), `lib/utils.ts` (`parseUtc`), `lib/theme.ts`.

Layout: content max width 6xl (1152px), 16px gutter on mobile, tables scroll horizontally inside their card.

## 5. Verified
- In the browser on real scans: report, fixes (approve / reject), history, leaderboard, Discovery tab, agent player with the page shown in the sandboxed iframe, partial report (outletcars.es) with its "Scan it anyway" card.
- Build: `tsc` + `vite build` pass. API tests: 272 green. Docker image runs and serves UI and API.

Not verified: tablet width (900), light theme of the newest components, keyboard navigation of the player, contrast measurements, the type-confirmation screen after the latest changes, the "ignore robots.txt" scan from the UI.

## 6. Remaining work (in order; cut from the bottom)
| # | Item | Notes |
|---|---|---|
| 1 | ~~"Not adopted" label~~ **done**: `not_adopted` checks show a dashed "Not adopted" badge with the opportunity text and rank after real defects in Top findings | |
| 2 | ~~Hide "Review fixes" when there are none~~ **done** (`fixes_count` on the scan payload) | |
| 3 | Mobile pass **done at 390 px** (header fits, player and tables do not overflow); still open: tablet (900), keyboard and contrast check, light theme of Discovery and the player | |
| 4 | Error states in the browser (WAF, unreachable, timeout) | use real failing domains |
| 5 | Live progress during a scan (pages found, checks completing) | design: in-memory events per scan id, `progress` field on `GET /api/scans/{id}`; optional |
| 6 | Example report on Home (clearly labelled) | optional |
| 7 | Paywall demo (`access_level`, blur) | cut unless time remains |
| 8 | Open Graph image, page titles per route | polish |

## 7. Risks
| Risk | Mitigation |
|---|---|
| Scans take up to a few minutes (journeys, retries) | progress stepper with explicit wait text; typed `TIMEOUT` explained |
| Sites blocked by a WAF or robots.txt in the demo | pick demo sites that scan cleanly; the partial report turns a robots.txt block into a finding |
| Hosted demo fails during judging | pre-generate reports for the demo sites as a fallback; video as the primary artefact |
| Text and pages from scanned sites (XSS, framing) | React text nodes only; third-party pages only through `/api/scans/{id}/page` (recorded URLs, scripts stripped, CSP sandbox, iframe sandbox) |
| Cost of public scans | rate limit exists; cap spend on the Meta key; `ALLOW_IGNORE_ROBOTS=false` on a public deploy |
