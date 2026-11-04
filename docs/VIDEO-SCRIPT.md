# Demo video script (target 2:54)

Voice-over in English, burned-in subtitles, 1080p. Everything shown is a real scan made by the product. The premise, in one line:
**being recommended gets the agent to the door; AX Scanner checks whether the door opens.**

Subtitle files with estimated timing: [`video/ax-scanner-demo.en.srt`](video/ax-scanner-demo.en.srt) and [`video/ax-scanner-demo.en.vtt`](video/ax-scanner-demo.en.vtt). Retime them against the final voice-over.

## Sites used

| Scene | Site | Why |
|---|---|---|
| 2, 3, 4, 5 | `autotorino.it` (Italian dealer) | One site for the whole story. Muse picks pages from an Italian homepage (5 of 6 categories found). The agent cannot reach a single vehicle page from the used-car list and stops in a loop. Seven fixes (JSON-LD, llms.txt) |
| 4 (contrast) | `flexicar.es` (Spanish dealer) | The same task passes: price, mileage and the page agree. Shown briefly so the failure is not the only outcome |
| 6 | leaderboard | Several scanned sites across types |

Other scanned dealers, for B-roll or a backup: `hahn-gruppe.de` (DE), `jeanlain.com` (FR), `lithia.com` and `sonicautomotive.com` (US), `arnoldclark.com` (UK), `clicars.com` (ES). `toyota.ro` (importer) has a clean 404-then-loop path.

## Scenes

| # | Time | On screen | Caption | Voice-over |
|---|---|---|---|---|
| 1 | 0:00-0:14 | Two boxes: "AI mentions" (ticked), then "Can the agent act?" (question mark). Cut to the home page. | Everyone asks if AI mentions their brand. What happens next? | Everyone is asking whether AI assistants mention their brand. Almost nobody asks what happens next: the agent opens the site. Can it act? AX Scanner measures exactly that. |
| 2 | 0:14-0:28 | Type `autotorino.it` (an Italian dealer) and start the scan: the placeholder animation with dashed page nodes. | Muse Spark identifies the site type | Paste a URL. Muse Spark identifies what kind of site it is, and the scanner looks for the pages that matter for that type. This one is an Italian dealer. |
| 3 | 0:28-0:46 | Report, Map tab: nodes turn green, one red; click a node marked "found by Muse". | Pages found by Muse, by rules, or both | Muse reads the homepage links, in any language, and picks each page. Keyword rules fill the gaps. Here it found five of six categories, and each one says who found it. |
| 4 | 0:46-1:25 | Agent path, step by step: "Muse's reason", "reasoned N tokens", the loop on the used-car list, the failed result. | A Muse agent tries a real task. This is the step after the recommendation. | Then a Muse agent gets a real task: find a used car under thirty thousand euros, and report its price, mileage and VIN. At every step it explains its move, and the API tells us how many tokens it reasoned with. According to the agent, the used-car list shows no links to individual vehicles, so it goes back, retries, and runs in circles. The check fails. Its answers are always verified against the real page. |
| 5 | 1:25-1:41 | A card with the real code of one agent step (app/journey/agent.py, the structured call to Muse) and the README table "How Muse Spark is used". | Muse decides. Code verifies. | Under the hood, every agent step is one structured call to Muse Spark: it picks a move and says why. The checks are plain code, and every answer is verified against the real page. |
| 6 | 1:41-2:20 | Fixes page: a JSON-LD fix, then "Generate prompt for fixes with Meta Muse Spark", the generated prompt. | Muse writes the fix prompt for your developer | For every gap we propose fixes, here seven: JSON-LD and llms.txt. Muse turns them into a ready prompt for your coding assistant, with the site's context, or you can email them to your developer. Nothing is exported until you approve it. |
| 7 | 2:20-2:42 | A second dealer where the same task passed, then the leaderboard with dealers, importers and shops. | Automatic, indicative scores | Every scan lands on a leaderboard, so brands and dealers can see where they stand. Another Spanish dealer passed the same task. |
| 8 | 2:42-2:54 | End card: github.com/ddul001/ax-scanner, "Built with Meta Model API · Muse Spark", Aivexia Tech. | Recommended gets them to the door. We check whether it opens. | Recommended gets them to the door. We check whether it opens. Built with the Meta Model API and Muse Spark, open source under MIT. |

## Say / do not say

- Say "the reason Muse gives with each move". The API reports how many tokens the model reasoned with, not the reasoning text.
- Attribute observations about a site to the agent ("according to the agent"). It may be wrong, for example when a page needs JavaScript.
- Do not claim vision (prices inside images) or search grounding: they are not built.
- Do not claim to measure mentions or recommendations: AX Scanner scores what happens after them.
- Present scores of real sites as automatic and indicative. Show the failed agent run as it is.

## Before recording

- Open the finished scan of each site above in its own tab (report, Map tab, Fixes page) so no scene waits for a scan.
- Start one scan live only to show the animation; speed up or cut the wait (a scan can take up to two minutes). Agents are not deterministic, so use the recorded scan for the results.
- 1080p, browser zoom 110-125%, no bookmarks bar, no terminal or key material on screen.
