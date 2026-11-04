import { useState } from "react";
import { ChevronDown, CircleDashed, CircleDot, CircleCheck, CircleX, ShieldAlert } from "lucide-react";
import { AgentPlayer } from "@/components/AgentPlayer";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";
import { label, type CheckResult, type Report, type Status } from "@/lib/api";

const STATUS: Record<Status, { text: string; tone: "ok" | "warn" | "fail" | "dashed"; Icon: typeof CircleCheck }> = {
  pass: { text: "Pass", tone: "ok", Icon: CircleCheck },
  fail: { text: "Fail", tone: "fail", Icon: CircleX },
  warn: { text: "Warn", tone: "warn", Icon: CircleDot },
  na: { text: "N/A", tone: "dashed", Icon: CircleDashed },
  skipped: { text: "Not active", tone: "dashed", Icon: CircleDashed },
};

export const StatusBadge = ({ status, notAdopted }: { status: Status; notAdopted?: boolean }) => {
  if (notAdopted && status === "fail")  // an opportunity, not a defect: the protocol is simply not adopted yet
    return <Badge tone="dashed" title="Not adopted yet: an opportunity, it does not cap the grade"><CircleDashed className="size-3" />Not adopted</Badge>;
  const style = STATUS[status];
  return (
    <Badge tone={style.tone}>
      <style.Icon className="size-3" />
      {style.text}
    </Badge>
  );
};

export const scoreColor = (n: number | null) => (n == null ? "bg-muted-foreground/40" : n >= 75 ? "bg-ok" : n >= 50 ? "bg-warn" : "bg-fail");
const gradeColor = (g: string) =>
  g === "A" || g === "B" ? "text-ok border-ok/40 bg-ok/10" : g === "C" ? "text-warn border-warn/40 bg-warn/10" : "text-fail border-fail/40 bg-fail/10";

export function ScoreCard({ report }: { report: Report }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-muted-foreground">AX Score</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex items-end gap-4">
          <div className="text-6xl leading-none font-bold tracking-tight tabular-nums">
            {Math.round(report.ax_score)}
            <span className="text-2xl font-medium text-muted-foreground"> / 100</span>
          </div>
          <div className={cn("grid size-14 place-items-center rounded-lg border text-3xl font-bold", gradeColor(report.grade))} aria-label={`Grade ${report.grade}`}>
            {report.grade}
          </div>
        </div>
        {report.gate_applied && (
          <div className="mt-4 flex gap-2 rounded-md border border-warn/40 bg-warn/10 p-3 text-sm">
            <ShieldAlert className="mt-0.5 size-4 shrink-0 text-warn" />
            <p>
              Would be <b>{report.grade_before_gate}</b>, capped at <b>{report.grade}</b> by a failed critical check:{" "}
              <span className="font-mono text-xs">{report.gate_checks.join(", ")}</span>
            </p>
          </div>
        )}
        <p className="mt-4 text-xs text-muted-foreground">
          {report.coverage.scored} of {report.coverage.total} checks scored · rules {report.version}
        </p>
      </CardContent>
    </Card>
  );
}

export function LayerBars({ report }: { report: Report }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-muted-foreground">Layers</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3.5">
        {report.layers.map((layer) => (
          <div key={layer.layer}>
            <div className="mb-1 flex items-baseline justify-between text-sm">
              <span className="font-medium">
                {label(layer.layer)} <span className="font-normal text-muted-foreground">· {Math.round(layer.weight)}%</span>
              </span>
              <span className="tabular-nums">{layer.score == null ? <span className="text-muted-foreground">n/a</span> : Math.round(layer.score)}</span>
            </div>
            <Progress value={layer.score ?? 0} barClass={scoreColor(layer.score)} />
            <p className="mt-1 text-xs text-muted-foreground">
              {layer.applicable} of {layer.checks} checks scored
            </p>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

const SEV_ORDER: Record<string, number> = { CRITICAL: 0, HIGH: 1, MAJOR: 2, MINOR: 3, INFO: 4 };
const bySeverity = (a: CheckResult, b: CheckResult) => (SEV_ORDER[a.severity] ?? 9) - (SEV_ORDER[b.severity] ?? 9);

export function Findings({ results }: { results: CheckResult[] }) {
  const top = results
    .filter((r) => r.status === "fail" || r.status === "warn")
    .sort((a, b) => Number(a.not_adopted) - Number(b.not_adopted) || bySeverity(a, b) || (a.status === "fail" ? -1 : 1))  // real defects first, opportunities after
    .slice(0, 3);
  if (!top.length) return null;
  return (
    <section aria-labelledby="top-findings">
      <h2 id="top-findings" className="mb-3 text-lg font-semibold tracking-tight">
        Top findings
      </h2>
      <div className="grid gap-3 md:grid-cols-3">
        {top.map((result) => (
          <Card key={result.check_id}>
            <CardContent className="space-y-2 pt-5">
              <div className="flex items-center justify-between">
                <StatusBadge status={result.status} notAdopted={result.not_adopted} />
                <Badge tone="outline">{result.severity}</Badge>
              </div>
              <p className="text-sm leading-snug font-medium">{result.summary || result.check_id}</p>
              <p className="font-mono text-xs text-muted-foreground">{result.check_id}</p>
            </CardContent>
          </Card>
        ))}
      </div>
    </section>
  );
}

const List = ({ title, items }: { title: string; items: string[] }) =>
  items.length ? (
    <div>
      <p className="mb-1 text-xs font-medium tracking-wide text-muted-foreground uppercase">{title}</p>
      <ul className="space-y-0.5 font-mono text-xs">
        {items.slice(0, 8).map((item) => (
          <li key={item} className="break-all">
            {item}
          </li>
        ))}
      </ul>
    </div>
  ) : null;

function CheckRow({ result }: { result: CheckResult }) {
  const [open, setOpen] = useState(false);
  return (
    <Collapsible open={open} onOpenChange={setOpen} className="border-b last:border-0">
      <CollapsibleTrigger className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-muted/50">
        <StatusBadge status={result.status} notAdopted={result.not_adopted} />
        <Badge tone="outline" className="hidden sm:inline-flex">
          {result.severity}
        </Badge>
        <span className="min-w-0 flex-1">
          <span className="block font-mono text-xs text-muted-foreground">{result.check_id}</span>
          <span className="block truncate text-sm">{result.summary || "-"}</span>
        </span>
        <ChevronDown className={cn("size-4 shrink-0 text-muted-foreground transition-transform", open && "rotate-180")} />
      </CollapsibleTrigger>
      <CollapsibleContent className="grid gap-4 bg-muted/40 px-4 py-4 sm:grid-cols-2">
        <List title="Found" items={result.found} />
        <List title="Missing" items={result.missing} />
        <List title="Pages checked" items={result.pages} />
        {result.not_adopted && (
          <p className="text-sm sm:col-span-2"><b>Opportunity:</b> {String(result.details?.opportunity ?? "Not adopted yet. Adopting it would raise this layer; it does not cap the grade.")}</p>
        )}
        {result.snippet && (
          <div className="sm:col-span-2">
            <p className="mb-1 text-xs font-medium tracking-wide text-muted-foreground uppercase">Evidence</p>
            <pre className="max-h-40 overflow-auto rounded-md border bg-card p-3 font-mono text-xs whitespace-pre-wrap">{result.snippet}</pre>
          </div>
        )}
      </CollapsibleContent>
    </Collapsible>
  );
}

export function CheckList({ report }: { report: Report }) {
  const [layer, setLayer] = useState("all");
  const [status, setStatus] = useState("all");
  const rows = report.results.filter((r) => (layer === "all" || r.layer === layer) && (status === "all" || r.status === status)).sort(bySeverity);
  const sel = "h-9 rounded-md border bg-card px-2 text-sm";
  return (
    <Card>
      <div className="flex flex-wrap items-center gap-2 border-b p-3">
        <select className={sel} value={layer} onChange={(e) => setLayer(e.target.value)} aria-label="Filter by layer">
          <option value="all">All layers</option>
          {report.layers.map((l) => (
            <option key={l.layer} value={l.layer}>
              {label(l.layer)}
            </option>
          ))}
        </select>
        <select className={sel} value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Filter by status">
          <option value="all">All statuses</option>
          {(["fail", "warn", "pass", "na", "skipped"] as Status[]).map((s) => (
            <option key={s} value={s}>
              {STATUS[s].text}
            </option>
          ))}
        </select>
        <span className="ml-auto text-xs text-muted-foreground">
          {rows.length} of {report.results.length} checks
        </span>
      </div>
      {rows.length ? rows.map((r) => <CheckRow key={r.check_id} result={r} />) : <p className="p-6 text-sm text-muted-foreground">No checks match these filters.</p>}
    </Card>
  );
}

interface Step {
  idx: number;
  action: string;
  thought: string;
  url: string;
  status: number;
  blockers: string[];
}
interface Run {
  task_id: string;
  goal: string;
  stop_reason: string;
  steps: Step[];
  answer?: { text?: string } | null;
}

export function Journeys({ report, scanId }: { report: Report; scanId?: number }) {
  const runs: Run[] = report.results.map((r) => r.details?.journey).filter(Boolean);
  if (!runs.length) return <p className="text-sm text-muted-foreground">No agent journey was recorded for this scan.</p>;
  if (scanId !== undefined && runs.some((run) => (run.steps as unknown as { view?: unknown }[]).some((s) => s.view))) return <AgentPlayer report={report} scanId={scanId} />;
  return (
    <div className="space-y-5">
      <p className="text-sm text-muted-foreground">A simulated agent tries real tasks on the site. It only reads pages and follows robots.txt.</p>
      {runs.map((run) => (
        <Card key={run.task_id}>
          <CardHeader>
            <CardTitle>{run.goal}</CardTitle>
            <p className="text-xs text-muted-foreground">
              Stopped: {run.stop_reason} · {run.steps.length} steps
            </p>
          </CardHeader>
          <CardContent>
            <ol className="space-y-4 border-l pl-5">
              {run.steps.map((step) => (
                <li key={step.idx} className="relative">
                  <span className="absolute -left-[27px] top-1 size-2.5 rounded-full border-2 border-primary bg-card" />
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone="primary">{step.action}</Badge>
                    {step.status > 0 && <Badge tone={step.status < 400 ? "ok" : "fail"}>HTTP {step.status}</Badge>}
                  </div>
                  {step.thought && <p className="mt-1.5 text-sm">{step.thought}</p>}
                  {step.url && <p className="mt-1 font-mono text-xs break-all text-muted-foreground">{step.url}</p>}
                  {step.blockers?.length > 0 && <p className="mt-1 text-xs text-fail">Blocked: {step.blockers.join(", ")}</p>}
                </li>
              ))}
            </ol>
            {run.answer?.text && (
              <p className="mt-4 rounded-md border bg-muted/50 p-3 text-sm">
                <b>Agent answer:</b> {run.answer.text}
              </p>
            )}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
