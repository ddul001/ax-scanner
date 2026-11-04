import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  AlertTriangle, ArrowRight, Bot, Building2, Car, Compass, FileCheck2, Layers, ListChecks, Lock, PlayCircle, ShoppingCart, Trophy,
} from "lucide-react";
import { api, ApiError, type LeaderboardEntry } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

const STEPS = [
  { Icon: ListChecks, title: "Classify", text: "We tell a dealer, a brand or importer site and an online shop apart, and pick the matching rules." },
  { Icon: Compass, title: "Discover", text: "An LLM reads your menu the way an agent would and picks the pages that matter, in any language. Keyword rules fill the gaps." },
  { Icon: Bot, title: "Check and try", text: "Code checks structured data, prices, contact and protocols. Then an agent attempts a real task: find a car, a dealer or a product." },
  { Icon: FileCheck2, title: "Report", text: "A score over 7 layers, evidence for every check and fixes you approve before anything is exported." },
];

const OUTPUTS = [
  { Icon: Layers, title: "Score and layers", text: "Discovery, Identity, Data, Actions, Trust, Agent UX and Protocol, each with plain-language findings and the evidence behind them." },
  { Icon: Compass, title: "Discovery map", text: "For every category (stock, test drive, dealer network, delivery...) the page we found, who found it and why." },
  { Icon: PlayCircle, title: "Agent replay", text: "Step through the agent's attempt: what it was shown, which link it chose, and the same page without JavaScript." },
  { Icon: FileCheck2, title: "Fixes you approve", text: "JSON-LD, llms.txt and robots.txt drafts for dealers, with what to verify. Nothing is exported until you approve it." },
];

const TYPES = [
  { Icon: Car, name: "Dealers", text: "Stock pages, vehicle and offer data, price consistency, test drive." },
  { Icon: Building2, name: "Brand and importer sites", text: "Model range, dealer network readable in HTML, test-drive form, configurator." },
  { Icon: ShoppingCart, name: "Online shops", text: "Product data and offers, delivery and returns terms, cart and checkout detected, never used." },
];

const gradeTone = (grade: string) => (grade === "A" || grade === "B" ? "text-ok border-ok/40 bg-ok/10" : grade === "C" ? "text-warn border-warn/40 bg-warn/10" : "text-fail border-fail/40 bg-fail/10");

function Latest({ rows }: { rows: LeaderboardEntry[] }) {
  return (
    <section aria-labelledby="latest" className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h2 id="latest" className="flex items-center gap-2 text-xl font-semibold tracking-tight"><Trophy className="size-5 text-primary" />Latest results</h2>
          <p className="text-sm text-muted-foreground">Real scans from this server, best score first.</p>
        </div>
        <Button asChild variant="ghost" size="sm"><Link to="/leaderboard">Full leaderboard<ArrowRight /></Link></Button>
      </div>
      <Card>
        <ul>
          {rows.map((row) => (
            <li key={row.scan_id} className="border-b last:border-0">
              <Link to={`/scan/${row.scan_id}`} className="flex items-center gap-3 px-4 py-3 hover:bg-muted/40">
                <span className="w-5 font-mono text-xs text-muted-foreground">{row.rank}</span>
                <span className="min-w-0 flex-1 truncate font-medium">{row.domain}</span>
                {row.type && <Badge tone="primary" className="hidden sm:inline-flex">{row.type}</Badge>}
                <span className={cn("grid size-8 place-items-center rounded-md border text-sm font-bold", gradeTone(row.grade))}>{row.grade}</span>
                <span className="w-8 text-right tabular-nums">{Math.round(row.ax_score)}</span>
              </Link>
            </li>
          ))}
        </ul>
      </Card>
    </section>
  );
}

export default function Home() {
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [llmOk, setLlmOk] = useState(true);
  const [robotsOverride, setRobotsOverride] = useState(false);
  const [ignoreRobots, setIgnoreRobots] = useState(false);
  const [latest, setLatest] = useState<LeaderboardEntry[]>([]);
  const nav = useNavigate();
  useEffect(() => { api.health().then((health) => (setLlmOk(health.llm_configured), setRobotsOverride(health.ignore_robots_allowed === true))).catch(() => {}); }, []);
  useEffect(() => { api.leaderboard().then((res) => setLatest(res.entries.slice(0, 5))).catch(() => {}); }, []);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setErr(null);
    setBusy(true);
    try {
      const { scan_id } = await api.createScan(url.trim(), false, ignoreRobots);
      nav(`/scan/${scan_id}`);
    } catch (error) {
      setErr(error instanceof ApiError ? error.message : "Could not reach the server.");
      setBusy(false);
    }
  }

  return (
    <div className="space-y-16">
      <section className="mx-auto max-w-3xl pt-8 text-center sm:pt-14">
        <p className="mb-4 inline-block rounded-full border bg-card px-3 py-1 text-xs font-medium text-muted-foreground">
          Agent-readiness audit for automotive websites
        </p>
        <h1 className="text-4xl font-bold tracking-tight sm:text-5xl">Can an AI agent find, understand and act on your website?</h1>
        <p className="mx-auto mt-5 max-w-2xl text-lg text-muted-foreground">
          AX Scanner opens your site the way an agent would, scores how ready it is, shows how it found each page and replays the agent's attempt step by step.
        </p>
        {!llmOk && (
          <div role="alert" className="mx-auto mt-6 flex max-w-xl gap-2 rounded-md border border-warn/40 bg-warn/10 p-3 text-left text-sm">
            <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warn" />
            <p><b>Scanning is disabled.</b> The server has no <span className="font-mono text-xs">META_API_KEY</span>. Set it in the environment and restart.</p>
          </div>
        )}
        <form onSubmit={submit} className="mx-auto mt-8 flex max-w-xl flex-col gap-3 sm:flex-row">
          <Input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="yourdealership.com" aria-label="Website URL" required autoFocus />
          <Button size="lg" type="submit" disabled={busy || !url.trim() || !llmOk} className="shrink-0">
            {busy ? "Starting..." : "Scan site"}
            <ArrowRight />
          </Button>
        </form>
        {robotsOverride && (
          <label className="mx-auto mt-3 flex max-w-xl items-start gap-2 text-left text-xs text-muted-foreground">
            <input type="checkbox" className="mt-0.5" checked={ignoreRobots} onChange={(e) => setIgnoreRobots(e.target.checked)} />
            Ignore robots.txt for this scan. Only for a site I own or have permission to scan; the report will say so.
          </label>
        )}
        {err && (
          <p role="alert" className="mt-3 text-sm text-fail">
            {err}
          </p>
        )}
        <p className="mt-3 flex flex-wrap items-center justify-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
          <span className="inline-flex items-center gap-1"><Lock className="size-3" />Read-only: never submits forms or logs in</span>
          <span>Respects robots.txt</span>
          <span>A scan takes a few minutes</span>
        </p>
      </section>

      <section aria-labelledby="how" className="space-y-5">
        <div className="text-center">
          <h2 id="how" className="text-xl font-semibold tracking-tight">How a scan works</h2>
          <p className="text-sm text-muted-foreground">The checks are code. The model is used where reading and judgement are needed.</p>
        </div>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {STEPS.map((step, i) => (
            <Card key={step.title}>
              <CardContent className="pt-5">
                <div className="mb-3 flex items-center gap-3">
                  <span className="grid size-9 place-items-center rounded-md bg-primary/10 text-primary"><step.Icon className="size-5" /></span>
                  <span className="font-mono text-xs text-muted-foreground">0{i + 1}</span>
                </div>
                <h3 className="font-semibold">{step.title}</h3>
                <p className="mt-1 text-sm text-muted-foreground">{step.text}</p>
              </CardContent>
            </Card>
          ))}
        </div>
      </section>

      <section aria-labelledby="types" className="space-y-5">
        <div className="text-center">
          <h2 id="types" className="text-xl font-semibold tracking-tight">Built for three kinds of automotive site</h2>
          <p className="text-sm text-muted-foreground">We detect which one you are and apply its own rules.</p>
        </div>
        <div className="grid gap-4 md:grid-cols-3">
          {TYPES.map((type) => (
            <Card key={type.name}>
              <CardContent className="flex gap-3 pt-5">
                <type.Icon className="mt-0.5 size-5 shrink-0 text-primary" />
                <div>
                  <h3 className="font-semibold">{type.name}</h3>
                  <p className="mt-1 text-sm text-muted-foreground">{type.text}</p>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      </section>

      <section aria-labelledby="gets" className="space-y-5">
        <div className="text-center">
          <h2 id="gets" className="text-xl font-semibold tracking-tight">What you get</h2>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          {OUTPUTS.map((output) => (
            <Card key={output.title}>
              <CardContent className="flex gap-3 pt-5">
                <span className="grid size-9 shrink-0 place-items-center rounded-md bg-primary/10 text-primary"><output.Icon className="size-5" /></span>
                <div>
                  <h3 className="font-semibold">{output.title}</h3>
                  <p className="mt-1 text-sm text-muted-foreground">{output.text}</p>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      </section>

      {latest.length >= 3 && <Latest rows={latest} />}
    </div>
  );
}
