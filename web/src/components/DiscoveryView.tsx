import { AlertTriangle, Check, CircleDashed, ExternalLink, Globe, Search, X } from "lucide-react";
import type { Discovery, DiscoveryRow, Report } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";

const SOURCE: Record<DiscoveryRow["source"], { text: string; tone: "primary" | "neutral" | "ok" | "dashed" }> = {
  llm: { text: "Found by LLM", tone: "primary" },
  both: { text: "LLM + rules agree", tone: "ok" },
  rules: { text: "Found by rules", tone: "neutral" },
  none: { text: "Not found", tone: "dashed" },
};

function StateIcon({ row }: { row: DiscoveryRow }) {
  if (row.state === "found") return <Check className="size-4 text-ok" aria-label="found" />;
  if (row.state === "rejected") return <AlertTriangle className="size-4 text-warn" aria-label="rejected" />;
  if (row.state === "external") return <Globe className="size-4 text-muted-foreground" aria-label="on another domain" />;
  if (row.state === "unreadable") return <X className="size-4 text-fail" aria-label="could not be read" />;
  return <CircleDashed className="size-4 text-muted-foreground" aria-label="not found" />;
}

function UsedBy({ ids }: { ids: string[] }) {
  if (!ids.length) return null;
  return (
    <p className="mt-2 flex flex-wrap items-center gap-1 text-xs text-muted-foreground">
      Used by
      {ids.map((check) => <span key={check} className="rounded border bg-muted px-1.5 py-0.5 font-mono">{check}</span>)}
    </p>
  );
}

function Row({ row }: { row: DiscoveryRow }) {
  const src = SOURCE[row.source];
  return (
    <li className="flex gap-3 border-b px-4 py-3 last:border-0">
      <span className="mt-0.5"><StateIcon row={row} /></span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium">{row.label}</span>
          <Badge tone={src.tone}>{src.text}</Badge>
          {row.state === "rejected" && <Badge tone="warn">LLM pick rejected</Badge>}
          {row.state === "external" && <Badge tone="outline">Other domain, not scanned</Badge>}
          {row.http_status != null && row.read && <span className="font-mono text-xs text-muted-foreground">HTTP {row.http_status}</span>}
        </div>
        {row.url ? (
          <a href={row.url} target="_blank" rel="noreferrer" className="mt-1 inline-flex max-w-full items-center gap-1 break-all font-mono text-xs text-primary hover:underline">
            {row.url}<ExternalLink className="size-3 shrink-0" />
          </a>
        ) : null}
        <p className="mt-1 text-sm text-muted-foreground">{row.how}</p>
        {row.reason && <p className="mt-1 text-xs italic text-muted-foreground">Why: “{row.reason}”</p>}
        <UsedBy ids={row.used_by} />
      </div>
    </li>
  );
}

function Stat({ n, label }: { n: number | string; label: string }) {
  return (
    <div>
      <p className="text-2xl font-bold tabular-nums">{n}</p>
      <p className="text-xs text-muted-foreground">{label}</p>
    </div>
  );
}

export function DiscoveryView({ report }: { report: Report }) {
  const d: Discovery | undefined = report.coverage.discovery;
  if (!d) {
    return (
      <Card><CardContent className="flex gap-3 pt-6 text-sm text-muted-foreground">
        <Search className="mt-0.5 size-4 shrink-0" />
        <p>This scan was made before discovery details were recorded. Scan again to see how each page was found.</p>
      </CardContent></Card>
    );
  }
  const summary = d.summary;
  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="space-y-4 pt-5">
          <p className="text-sm text-muted-foreground">
            {d.mode === "llm_first"
              ? "An LLM read the homepage links and chose the page for each category, the way an agent would open the menu. Keyword rules fill in what it left empty, and a pick whose page does not match its category is rejected."
              : "No LLM was used for this scan: every page was found by keyword rules on the URLs."}
          </p>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4 lg:grid-cols-7">
            <Stat n={`${summary.found}/${summary.categories}`} label="categories found" />
            <Stat n={summary.by_llm} label="by the LLM" />
            <Stat n={summary.by_rules} label="by rules" />
            <Stat n={summary.rejected} label="LLM picks rejected" />
            <Stat n={summary.not_found} label="not found" />
            <Stat n={d.sources.pages_read} label="pages read" />
            <Stat n={d.sources.sitemap_urls} label="sitemap URLs" />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-base">Categories</CardTitle></CardHeader>
        <CardContent className="p-0"><ul>{d.roles.map((row) => <Row key={row.role} row={row} />)}</ul></CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-2">
            <CardTitle className="text-base">{d.items.label} ({d.items.urls.length})</CardTitle>
            <Badge tone={d.items.source === "llm" ? "primary" : d.items.urls.length ? "neutral" : "dashed"}>
              {d.items.source === "llm" ? "Found by LLM" : d.items.urls.length ? "Found by rules" : "Not found"}
            </Badge>
            {d.items.fallback && <Badge tone="warn">rules fallback</Badge>}
          </div>
          <p className="text-sm text-muted-foreground">{d.items.how}</p>
        </CardHeader>
        <CardContent className="p-0">
          <ul>
            {d.items.urls.map((entry) => (
              <li key={entry.url} className="border-b px-4 py-2 last:border-0">
                <a href={entry.url} target="_blank" rel="noreferrer" className="inline-flex max-w-full items-center gap-1 break-all font-mono text-xs text-primary hover:underline">
                  {entry.url}<ExternalLink className="size-3 shrink-0" />
                </a>
                <span className="ml-2 font-mono text-xs text-muted-foreground">HTTP {entry.http_status || "error"}</span>
                <UsedBy ids={entry.used_by} />
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>

      <Collapsible>
        <CollapsibleTrigger className="text-sm text-muted-foreground underline-offset-2 hover:underline">All {d.pages.length} pages the scanner opened</CollapsibleTrigger>
        <CollapsibleContent>
          <Card className="mt-2"><CardContent className="p-0">
            <table className="w-full text-sm">
              <tbody>
                {d.pages.map((page) => (
                  <tr key={page.url} className="border-b last:border-0">
                    <td className="px-4 py-2 font-mono text-xs text-muted-foreground">{page.role}</td>
                    <td className="break-all px-4 py-2 font-mono text-xs">{page.url}</td>
                    <td className="whitespace-nowrap px-4 py-2 text-right font-mono text-xs text-muted-foreground">{page.http_status || "error"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent></Card>
        </CollapsibleContent>
      </Collapsible>
    </div>
  );
}
