# Deploying AX Scanner on Railway

One service: the `Dockerfile` builds the UI and the API into a single image (about 270 MB). `railway.json` already sets the Dockerfile builder,
one replica, the `/health` check and restart on failure.

## 1. Before you start

- Put a **spend limit** on the Meta Model API key. A public URL means strangers can start scans, and every scan makes Muse calls.
- Push the repository to GitHub (the service deploys from it).

## 2. Create the service

1. Railway: **New Project → Deploy from GitHub repo**, pick this repository. Railway reads `railway.json` and builds the `Dockerfile`.
2. **Volume:** add a volume to the service and mount it at `/data`. The image already points `DATABASE_URL` at `sqlite:////data/ax.db`,
   so scans and the leaderboard survive redeploys. Without a volume the database is wiped at every deploy.
3. **Variables** (service → Variables):

| Variable | Value | Why |
|---|---|---|
| `META_API_KEY` | your key | without it the server starts but refuses scans (the UI shows a banner) |
| `ALLOW_IGNORE_ROBOTS` | `false` | a public instance must not offer "scan ignoring robots.txt" |
| `MAX_SCANS_PER_DAY` | `150` | cap on new scans per rolling 24 h across all visitors; answers 429 `DAILY_LIMIT` afterwards. Existing scans stay browsable |
| `META_MODEL` | `muse-spark-1.3` (default) | change only if the model name changes |

   Railway sets `PORT` itself. Do not add more replicas: the rate limiter and the scan tasks live in the process.
4. **Networking → Generate Domain** to get the public URL.

## 3. Check it

```
curl https://<your-domain>/health
```
should return `{"ok":true,"ignore_robots_allowed":false,"llm_model":"muse-spark-1.3","llm_configured":true}`.
Open the URL, then `/leaderboard`, `/history`.

## 4. Fill it with scans

A fresh volume has no scans, so the leaderboard is empty. Seed it through the public API, exactly as a visitor would:

```
python scripts/seed_remote.py --base https://<your-domain>
```

14 sites, 3 at a time, about 10 minutes and the same number of scans against `MAX_SCANS_PER_DAY`. Use `--only a.com,b.com` for a few.
Sites that block the scanner end as failed scans; that is expected and shown to visitors as such.

## 5. What this setup already protects

- Visitors are rate limited per IP (10 scans a minute); the proxy headers are trusted so the limit sees the visitor, not Railway's proxy.
- Scans are read only, never submit forms, respect robots.txt, and refuse private or local addresses.
- Page views of third-party sites are stripped of scripts and served in a sandbox.

## 6. Known limits

- SQLite on one volume, a single replica: fine for a demo, not for load. `DATABASE_URL` accepts a Postgres URL if that changes.
- Pages that need JavaScript to show their content are read as a crawler without JavaScript would read them (Playwright is not in the image).
- The scanner identifies itself as `AivexiaScanBot` with a link to `https://aivexia.ro/bot`: make sure that page exists.
- The "Generate prompt" button calls Muse on every click; it is rate limited per IP but not counted in `MAX_SCANS_PER_DAY`.

## Verified locally

The image was built and run with a mounted `/data` volume, `ALLOW_IGNORE_ROBOTS=false` and `MAX_SCANS_PER_DAY=150`: `/health`, the UI and its client routes
answered, an "ignore robots" request was refused (403), and a real scan of a dealer site completed (score, page discovery, fixes and the Muse-written prompt).
