import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { AlertTriangle, Check, Loader2, RefreshCw, Wrench } from "lucide-react";
import { api, ApiError, isPartial, type Report, type Scan } from "@/lib/api";
import { PartialReportView } from "@/components/PartialReport";
import { SiteMap } from "@/components/SiteMap";
import { AgentPath } from "@/components/AgentPath";
import { DiscoveryView } from "@/components/DiscoveryView";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { CheckList, Findings, Journeys, LayerBars, ScoreCard } from "@/components/report";
import { cn, parseUtc } from "@/lib/utils";

const STEPS = [
  { key: "queued", label: "Queued" },
  { key: "classifying", label: "Identifying site type" },
  { key: "scanning", label: "Running checks and agent journeys" },
  { key: "completed", label: "Report ready" },
];
const rank = (status: Scan["status"]) => (status === "queued" ? 0 : status === "classifying" ? 1 : status === "completed" ? 3 : 2);

const ERRORS: Record<string, string> = {
  BLOCKED_BY_WAF: "The site blocks automated visitors, so we could not read it. That is itself a finding for AI agents, but we cannot score the rest.",
  UNREACHABLE: "We could not reach this site. Check the address and try again.",
  TIMEOUT: "The scan took too long and was stopped.",
};

function RescanButton({ domain, variant = "outline" }: { domain: string; variant?: "outline" | "default" }) {
  const nav = useNavigate();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  return (
    <div className="flex flex-col items-end gap-1">
      <Button
        variant={variant}
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          setErr(null);
          try {
            const { scan_id } = await api.createScan(domain, true);
            nav(`/scan/${scan_id}`);
          } catch (error) {
            setErr(error instanceof ApiError ? error.message : "Could not start the scan.");
            setBusy(false);
          }
        }}
      >
        {busy ? <Loader2 className="animate-spin" /> : <RefreshCw />}Scan again
      </Button>
      {err && <p role="alert" className="text-xs text-fail">{err}</p>}
    </div>
  );
}

const pageKey = (url: string) => { try { const parsed = new URL(url); return `${parsed.host}${parsed.pathname.replace(/\/$/, "")}`; } catch { return url; } };

/** Page categories whose page the agent opened in any of its runs (matched by URL against the discovery result). */
function agentVisits(report: Report): Set<string> {
  const urls = new Set(report.results.flatMap((result) => (result.details?.journey?.steps ?? []).map((step: { url: string }) => step.url)).filter(Boolean).map(pageKey));
  return new Set((report.coverage.discovery?.roles ?? []).filter((row) => row.url && urls.has(pageKey(row.url))).map((row) => row.role));
}

function Progress({ scan }: { scan: Scan }) {
  const at = rank(scan.status);
  return (
    <Card>
      <CardContent className="pt-6">
        <div className="flex items-center gap-3">
          <Loader2 className="size-5 animate-spin text-primary" />
          <div>
            <p className="font-medium">Scanning {scan.site.domain}</p>
            <p className="text-sm text-muted-foreground">This can take up to two minutes. Reading pages only, no forms are submitted.</p>
          </div>
        </div>
        {(scan.expected_pages?.length ?? 0) > 0 && scan.status !== "queued" && scan.status !== "classifying" && (
          <div className="mt-6"><SiteMap domain={scan.site.domain} categories={scan.expected_pages ?? []} /></div>
        )}
        <ol className="mt-6 space-y-3" aria-live="polite">
          {STEPS.map((step, i) => (
            <li key={step.key} className={cn("flex items-center gap-3 text-sm", i > at && "text-muted-foreground")}>
              <span className={cn("grid size-6 place-items-center rounded-full border text-xs", i < at && "border-ok bg-ok text-background", i === at && "border-primary text-primary")}>
                {i < at ? <Check className="size-3.5" /> : i + 1}
              </span>
              {step.label}
            </li>
          ))}
        </ol>
      </CardContent>
    </Card>
  );
}

function Confirm({ scan, onDone }: { scan: Scan; onDone: (s: Scan) => void }) {
  const alts = scan.classification?.alternatives ?? [];
  const [pick, setPick] = useState(alts[0]?.type ?? "dealer");
  const [busy, setBusy] = useState(false);
  return (
    <Card>
      <CardContent className="space-y-4 pt-6">
        <div>
          <h2 className="text-lg font-semibold">We are not sure what type of site this is</h2>
          <p className="text-sm text-muted-foreground">Pick the closest match so we apply the right checks.</p>
        </div>
        <div role="radiogroup" className="grid gap-2 sm:grid-cols-2">
          {alts.map((alt) => (
            <label key={alt.type} className={cn("flex cursor-pointer items-center justify-between rounded-md border p-3", pick === alt.type && "border-primary bg-primary/5")}>
              <span className="flex items-center gap-2 font-medium capitalize">
                <input type="radio" name="type" checked={pick === alt.type} onChange={() => setPick(alt.type)} />
                {alt.type}
              </span>
              <span className="text-sm text-muted-foreground">{Math.round(alt.probability * 100)}%</span>
            </label>
          ))}
        </div>
        <Button
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            onDone(await api.confirm(scan.id, pick));
          }}
        >
          Confirm and scan
        </Button>
      </CardContent>
    </Card>
  );
}

export default function ScanPage() {
  const id = Number(useParams().id);
  const [scan, setScan] = useState<Scan | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setScan(await api.getScan(id));
      setErr(null);
    } catch (error) {
      setErr(error instanceof Error ? error.message : "Failed to load");
    }
  }, [id]);

  useEffect(() => {
    load();
    const timer = setInterval(() => {
      setScan((current) => {
        if (!current || !["completed", "failed", "needs_confirmation"].includes(current.status)) load();
        return current;
      });
    }, 2000);
    return () => clearInterval(timer);
  }, [load]);

  if (err && !scan) return <p role="alert" className="text-fail">{err}</p>;
  if (!scan) return <Loader2 className="mx-auto mt-20 size-6 animate-spin text-muted-foreground" />;

  const header = (
    <div className="mb-6 flex flex-wrap items-center gap-3">
      <h1 className="text-2xl font-bold tracking-tight">{scan.site.domain}</h1>
      {scan.site.type && <Badge tone="primary">{scan.site.type}</Badge>}
      <span className="text-xs text-muted-foreground">Scan #{scan.id}</span>
    </div>
  );

  if (scan.status === "failed") {
    return (
      <div className="mx-auto max-w-2xl">
        {header}
        <Card>
          <CardContent className="flex gap-3 pt-6">
            <AlertTriangle className="mt-0.5 size-5 shrink-0 text-fail" />
            <div>
              <p className="font-medium">Scan failed {scan.error && <span className="font-mono text-xs text-muted-foreground">({scan.error.code})</span>}</p>
              <p className="mt-1 text-sm text-muted-foreground">{(scan.error && ERRORS[scan.error.code]) || scan.error?.message}</p>
              <div className="mt-4 flex flex-wrap items-start gap-2">
                <RescanButton domain={scan.site.domain} variant="default" />
                <Button asChild variant="outline"><Link to="/">Try another site</Link></Button>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  if (scan.status === "needs_confirmation") return <div className="mx-auto max-w-2xl">{header}<Confirm scan={scan} onDone={setScan} /></div>;
  if (scan.status === "completed" && isPartial(scan.report)) return <div className="mx-auto max-w-5xl">{header}<PartialReportView domain={scan.site.domain} report={scan.report} /></div>;
  if (scan.status !== "completed" || !scan.report) return <div className="mx-auto max-w-2xl">{header}<Progress scan={scan} /></div>;

  const report = scan.report as Report;
  const cls = scan.classification as (Scan["classification"] & { brands?: string[]; locations?: number; language?: string; method?: string }) | null;
  const pages = new Set(report.results.flatMap((result) => result.pages)).size;
  const facts: [string, string][] = [
    ["Scanned", parseUtc(scan.created_at).toLocaleString()],
    ["Pages examined", String(pages)],
    ["Site type", cls ? `${cls.type} (${Math.round(cls.confidence * 100)}% confidence)` : scan.site.type ?? "-"],
    ["Brands", cls?.brands?.length ? cls.brands.join(", ") : "-"],
    ["Locations", cls?.locations != null ? String(cls.locations) : "-"],
    ["Language", cls?.language ?? "-"],
    ["Checks", `${report.coverage.scored} scored of ${report.coverage.total} · rules ${report.version}${report.scoring_version ? ` · ${report.scoring_version}` : ""}`],
    ["Classified by", cls?.method ?? "-"],
    ["Analysed with", report.coverage.ai ? `${report.coverage.ai.provider}: ${report.coverage.ai.model}${report.coverage.ai.used_for.length ? ` (${report.coverage.ai.used_for.join(", ")})` : " (rules only)"}` : "-"],
  ];
  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>{header}</div>
        <div className="flex flex-wrap items-start gap-2">
          <RescanButton domain={scan.site.domain} />
          {(scan.fixes_count ?? 0) > 0 && (
            <Button asChild>
              <Link to={`/scan/${scan.id}/fixes`}><Wrench />Review fixes ({scan.fixes_count})</Link>
            </Button>
          )}
        </div>
      </div>
      <div className="grid gap-4 lg:grid-cols-[2fr_3fr]">
        {report.coverage.robots?.ignored && (
          <div role="note" className="rounded-md border border-warn/40 bg-warn/10 p-3 text-sm lg:col-span-2">
            <b>robots.txt was ignored for this scan</b> at the requester's request
            {report.coverage.robots.disallowed_for_scanner ? " (it did disallow our scanner)" : " (it did not actually block our scanner)"}.
          </div>
        )}
        <ScoreCard report={report} />
        <LayerBars report={report} />
      </div>
      <Card>
        <CardContent className="pt-5">
          <h2 className="mb-3 text-sm font-semibold text-muted-foreground">Scan details</h2>
          <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-2 lg:grid-cols-4">
            {facts.map(([label, value]) => (
              <div key={label}><dt className="text-xs uppercase tracking-wide text-muted-foreground">{label}</dt><dd className="text-sm break-words">{value}</dd></div>
            ))}
          </dl>
          <p className="mt-3 text-xs text-muted-foreground"><a href={scan.site.origin} target="_blank" rel="noreferrer noopener" className="text-primary hover:underline">{scan.site.origin}</a> · <Link to="/history" className="text-primary hover:underline">All scans</Link></p>
        </CardContent>
      </Card>
      <Findings results={report.results} />
      <Tabs defaultValue="checks">
        <TabsList>
          <TabsTrigger value="checks">Checks ({report.results.length})</TabsTrigger>
          <TabsTrigger value="journey">Agent journey</TabsTrigger>
          <TabsTrigger value="map">Map</TabsTrigger>
          <TabsTrigger value="discovery">Discovery</TabsTrigger>
        </TabsList>
        <TabsContent value="checks"><CheckList report={report} /></TabsContent>
        <TabsContent value="journey"><Journeys report={report} scanId={scan.id} /></TabsContent>
        <TabsContent value="map">
          <div className="grid gap-6 lg:grid-cols-2 lg:items-start">
            <div className="lg:sticky lg:top-20">
              {report.coverage.discovery
                ? <SiteMap domain={scan.site.domain} categories={scan.expected_pages ?? []} rows={report.coverage.discovery.roles} visited={agentVisits(report)} />
                : <p className="text-sm text-muted-foreground">No page discovery was recorded for this scan.</p>}
            </div>
            <div className="min-w-0"><AgentPath report={report} /></div>
          </div>
        </TabsContent>
        <TabsContent value="discovery"><DiscoveryView report={report} /></TabsContent>
      </Tabs>
    </div>
  );
}
