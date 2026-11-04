# AX Scanner - gap analysis against the requirements

**Date:** 2026-11-02 · **Deadline:** 4 Nov 20:00 Bucharest (official cut 5 Nov 06:30 IST = 03:00 Bucharest) · **Code:** 272 tests green, tree clean

## 0. What "requirements" means here, and what is missing
The repository holds three requirement sources: the **hackathon deliverables** and review verdict in `docs/PLAN.md` §1, the **MVP scope, acceptance criteria, paywall and Meta-usage** sections of `docs/MVP-PLAN.md` (§1, §8, §9, §10), and the **demo story** in `docs/PLAN.md` §9. The **official judging criteria and submission format are not in the repo** (still an open question in `docs/PLAN.md` §10): this analysis cannot confirm them. **Action 0: read the hackathon submission page and check each item below against it.**

Legend: **Done** · **Partial** · **Open** (not done, still wanted) · **Cut** (deliberately dropped, decision recorded).

## 1. Hackathon deliverables
| Requirement | Source | State | Evidence / gap |
|---|---|---|---|
| Public repo | PLAN §1 | **Open** | No git remote, no `LICENSE`. No secrets are tracked (`.env` is ignored; only `.env.example`). Needs: create the remote, add a license, push |
| README "Built with Meta Model API" | PLAN §1 | **Done** | `README.md`: where Muse Spark is used, what is not built |
| 2-3 minute video | PLAN §1 | **Open** | Not recorded. Storyboard in §5 |
| Official criteria, format, deploy required? | PLAN §10 | **Unknown** | Check the submission page. If a public URL is required, the deploy (Dockerfile + `railway.json`, verified locally) is the missing step |
| Meta API limits / credits | PLAN §10 | **Unknown** | One scan makes 1 classification call, 2 page-picking calls (3 for a shop, which also reads policies) and the agent journeys: up to 8 calls per attempt, 1-2 journeys, one more attempt after a loop. Set a spend cap on the key before a public deploy |

## 2. MVP scope (`MVP-PLAN` §1)
| Requirement | State | Evidence / gap |
|---|---|---|
| Step 0 classification (dealer / importer / ecommerce) with Muse Spark | **Done** | heuristics + Muse, confirmation below the threshold; an automotive site that Muse calls "unsupported" now asks instead of failing |
| Checks per type from `docs/checks/mvp/` (plan: 53 = dealer 19, importer 17, ecommerce 17) | **Partial** | Dealer 19 + 1 info; importer 15 + 4 info (**reduced variant**: no `act.locator_search`, `mod.schema_offer`; detections added); ecommerce 17 + 1 info. `act.add_to_cart` / `guest_checkout` are *detected, not executed* (read-only rule) |
| 7 layers, per-type weights, renormalisation | **Done** | `app/domain/scoring.py`, `app/templates/*.yaml` |
| Vision: price in an image | **Open** | Not built; `price_readable` reports `vision: deferred`. Muse vision is one of the plan's four Meta capabilities |
| Agent Journey, 1-2 tasks per type | **Done** | dealer 2, importer 1, shop 1; answers verified against the page; one more attempt after a loop / Muse error |
| Visibility (Muse grounded x3 + external engine) | **Cut** | Postponed by decision; feasibility proven (`/responses` + `web_search`, sources via `include`); about 70k tokens per call. Consequence: **AX = readiness only** (the plan's AX = 0.6 R + 0.4 V is not in effect) |
| Insights + fixes (JSON-LD, llms.txt, robots.txt, **Agent Card**) -> approval -> export | **Partial** | Dealer: JSON-LD, llms.txt, robots.txt, approve / reject / export approved only. **No fixes for importer or shop**; Agent Card fix not built; "insights" are the top-3 findings computed in the UI, not a server object |
| UI: scan, score, checks, insights, fixes, leaderboard | **Done** | plus History, Discovery tab, agent player, partial report |
| 20-site demo set | **Done as a count** | 23 domains with a completed scan (10 dealers, 12 importers, 1 shop). Plan mix was 14 / 3 / 3 |
| Free vs paid report (`access_level`, paywall) (§9) | **Cut candidate** | Not built. Payment was out of scope even in the plan; only the blurred-details demo was planned |

## 3. Acceptance criteria (`MVP-PLAN` §8)
| Criterion | State | Evidence / gap |
|---|---|---|
| Reproducibility: 3 scans, AX within +-5 | **Done, measured 2026-11-02** | 4 sites x 3 runs: spread 0 / 0 / 0 / 5.8 (autoworld.ro, a journey flips between pass and warn). A rescan of 19 sites after the rules changed moved some scores by 14-18 points: that was a version change plus model variance, not measured as a repeat |
| Classification >= 9/10 on the test set | **Partial, outdated** | Stored baseline (27 Oct, 50 domains): **40/50**; all 10 misses are sites that blocked the fetch (WAF / unreachable), so **40/40 where the site could be read**; 0/5 ecommerce reachable. Not re-run since the classifier and the "unsupported -> confirm" rule changed |
| Fix valid: JSON-LD passes the Schema.org validator | **Partial** | Structural validation only; the official validator was never run on the generated JSON-LD. The generator also drops template junk (`{{...}}`) it finds in the site's own markup |
| Safety: 0 forms submitted, 0 write tools, MCP URL only from discovery | **Done** | Tests assert GET-only for dealer, importer, shop and the demo; MCP is not called at all |
| Approval: no export without `approved` | **Done** | 409 `NO_APPROVED_FIXES`, tested |
| Demo: 20 sites scanned, ranked, with insights | **Done as a count** | Leaderboard marks scans made with older rules as "outdated"; rescan with `scripts/rescan_outdated.py --all` before recording |

## 4. Meta usage (`MVP-PLAN` §10)
| Muse Spark capability | State |
|---|---|
| Structured output | **In use**: classifier, link and page picking, policy reading, every agent step |
| Tool calling + browser | **Partial**: an agent loop with structured actions on a read-only no-JavaScript browser; not function calling, not a real browser |
| Vision | **Not built** |
| Search grounding | **Not built** (probed) |

Two of the four capabilities the plan promised to the judges are not in the product. Say so in the video rather than imply them.

## 5. Demo story (`PLAN` §9) - can each beat be shown today?
| Beat | State | How |
|---|---|---|
| 1 "AI agents now shop for cars. Can they read your site?" | Video | Open with the demo-site contrast (100 vs JS-only) |
| 2 Paste URL -> detected type | **Ready** | Home form; type + confidence + confirmation screen |
| 3 Score -> an insight such as "prices in images on 42/50 pages" | **Gap** | Price-in-image needs vision. Use a real finding instead: e.g. `ux.j_dealer` stuck on a JS-only dealer list, shown in the agent player |
| 4 JSON-LD fix -> re-scan | **Partial** | Fix review, approve, export and "Scan again" exist; the improvement cannot be shown on a real third-party site. Show the demo site (100) vs the same page with a JS-only list as the before/after |
| 5 Leaderboard: dealers vs importers vs ecommerce | **Partial** | Works; only one shop is ranked (3 others block the scanner) |
| 6 "Built on Muse Spark: ..." | **Done** | README table; only list what is in use |

## 6. Quality and operations
| Item | State | Note |
|---|---|---|
| Deploy | **Open (decision)** | Image builds (272 MB) and serves UI + API locally. Needs a service, a volume at `/data`, `META_API_KEY`, `ALLOW_IGNORE_ROBOTS=false`, one replica |
| Real-site agent results | **Partial** | `ux.j_dealer`: 1 of 12 real brand sites pass (dacia.ro, which failed on earlier runs); `ux.j_find`: 5 of 11 dealers pass. Clean positive case: the demo site |
| JavaScript-rendered sites | **Known limit** | The agent and the locator checks read HTML only; Playwright is optional and not in the image |
| WAF / robots blocked sites | **Known limit** | autodoc.es, automobilus.ro, peugeot.fr, outletcars.es. robots.txt gives a partial report |
| UI polish | **Mostly done** | "Not adopted" label, hidden empty "Review fixes", Meta attribution in the footer and the scan details, mobile pass at 390 px (header and player overflow fixed). Open: tablet, keyboard and contrast, light theme of the newest components |
| Stale documentation | **Done** | UI-PLAN updated 2026-11-02 |
| Live progress during a scan | **Open (optional)** | Designed (in-memory events), not built |

## 7. Recommended order until the deadline
| # | Task | Why | Effort |
|---|---|---|---|
| 0 | Read the official criteria and submission rules; confirm whether a public deploy is required | everything below depends on it | 15 min |
| 1 | Publish: git remote, `LICENSE`, push | "public repo" is a stated deliverable | 20 min |
| 2 | Rescan everything with the final code (`scripts/rescan_outdated.py --all`) and stop changing rules | a stable, comparable leaderboard for the recording | 20 min in the background |
| 3 | UI polish pass (label, hidden empty button, mobile) | avoids visible rough edges on camera | 1-1.5 h |
| 4 | Record the video, with the contrast story and a plain statement of what is and is not built | stated deliverable | 2-3 h |
| 5 | Deploy, if required or wanted | decided in step 0 | 1 h |
| 6 | Re-run the classification baseline and the official Schema.org validator on one generated JSON-LD | closes two acceptance criteria | 1 h |
| 7 | Only if time remains: more shops for the leaderboard, memorise Muse decisions per site, live scan progress | polish | - |

Not recommended before the deadline: Visibility, vision, Playwright, the paywall.
