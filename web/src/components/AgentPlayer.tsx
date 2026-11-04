import { useMemo, useState } from "react";
import { Bot, ChevronLeft, ChevronRight, Eye, EyeOff } from "lucide-react";
import type { JourneyRun, JourneyStep, Report } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

const ACTION_TEXT: Record<string, string> = {
  start: "Opens the homepage",
  open_link: "Opens a link",
  goto: "Goes to a URL",
  back: "Goes back",
  finish: "Finishes and answers",
};
const STATUS_TONE = { pass: "ok", warn: "warn", fail: "fail", skipped: "neutral", na: "neutral" } as const;

/** Which link of the page the agent chose when it acted next: by index ("link #3") or by URL (goto). */
function chosenLink(next: JourneyStep | undefined, view: NonNullable<JourneyStep["view"]>): number | null {
  if (!next) return null;
  const match = /^link #(\d+)$/.exec(next.target);
  if (match) return Number(match[1]);
  const hit = view.links.find((link) => link.url === next.target);
  return hit ? hit.i : null;
}

function path(url: string) {
  try {
    const u = new URL(url);
    return u.pathname + u.search;
  } catch {
    return url;
  }
}

function AnswerSummary({ answer }: { answer: Record<string, unknown> | null }) {
  if (!answer) return <p className="text-sm text-muted-foreground">The agent gave no answer.</p>;
  const rows = Object.entries(answer).filter(([key, value]) => value !== null && value !== "" && !(Array.isArray(value) && !value.length) && key !== "found");
  return (
    <div>
      <p className="mb-2 text-sm">{answer.found ? "The agent reports it found what it was asked for:" : "The agent reports it could not complete the task."}</p>
      <dl className="grid gap-x-4 gap-y-1 text-sm sm:grid-cols-[auto_1fr]">
        {rows.map(([key, value]) => (
          <div key={key} className="contents">
            <dt className="font-mono text-xs text-muted-foreground">{key}</dt>
            <dd className="break-words">{Array.isArray(value) ? value.join(", ") : String(value)}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

export function AgentPlayer({ report, scanId }: { report: Report; scanId: number }) {
  const runs = useMemo(() => {
    return report.results
      .filter((r) => r.details?.journey?.steps?.some((s: JourneyStep) => s.view))
      .map((r) => ({ result: r, run: r.details.journey as JourneyRun }));
  }, [report]);
  const [runIdx, setRunIdx] = useState(0);
  const [stepIdx, setStepIdx] = useState(0);
  const [showPage, setShowPage] = useState(true);  // shown by default; the choice sticks while stepping through the run
  if (!runs.length) return null;
  const { result, run } = runs[Math.min(runIdx, runs.length - 1)];
  const step = run.steps[Math.min(stepIdx, run.steps.length - 1)];
  const next = run.steps[stepIdx + 1];
  const view = step.view;
  const chosen = view ? chosenLink(next, view) : null;
  const go = (i: number) => setStepIdx(Math.max(0, Math.min(run.steps.length - 1, i)));
  const pageUrl = view?.url ? `/api/scans/${scanId}/page?url=${encodeURIComponent(view.url)}` : null;
  const checks = result.details?.verification?.checks as Record<string, boolean> | undefined;

  return (
    <div className="space-y-4">
      {runs.length > 1 && (
        <div className="flex flex-wrap gap-2" role="tablist" aria-label="Agent tasks">
          {runs.map((entry, i) => (
            <Button key={entry.run.task_id} size="sm" variant={i === runIdx ? "default" : "outline"} role="tab" aria-selected={i === runIdx}
              onClick={() => (setRunIdx(i), setStepIdx(0))}>
              {entry.result.check_id}
              <Badge tone={STATUS_TONE[entry.result.status as keyof typeof STATUS_TONE] ?? "neutral"} className="ml-1">{entry.result.status}</Badge>
            </Button>
          ))}
        </div>
      )}

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-start gap-2">
            <Bot className="mt-0.5 size-5 text-primary" />
            <div className="min-w-0 flex-1">
              <CardTitle className="text-base">{run.goal}</CardTitle>
              <p className="mt-1 text-sm text-muted-foreground">{result.summary}</p>
            </div>
            <Badge tone={STATUS_TONE[result.status as keyof typeof STATUS_TONE] ?? "neutral"}>{result.status}</Badge>
          </div>
          {checks && (
            <p className="mt-2 flex flex-wrap gap-1 text-xs">
              {Object.entries(checks).map(([k, ok]) => <Badge key={k} tone={ok ? "ok" : "fail"}>{ok ? "✓" : "✗"} {k.replace(/_/g, " ")}</Badge>)}
            </p>
          )}
        </CardHeader>
      </Card>

      <div className="flex items-center gap-2">
        <Button size="icon" variant="outline" onClick={() => go(stepIdx - 1)} disabled={stepIdx === 0} aria-label="Previous step"><ChevronLeft /></Button>
        <ol className="flex flex-1 flex-wrap gap-1" aria-label="Steps">
          {run.steps.map((s, i) => (
            <li key={s.idx}>
              <button onClick={() => go(i)} aria-current={i === stepIdx ? "step" : undefined}
                className={cn("rounded-md border px-2.5 py-1 text-xs", i === stepIdx ? "border-primary bg-primary/10 font-medium" : "text-muted-foreground hover:text-foreground")}>
                {s.idx}. {s.action.replace("_", " ")}
              </button>
            </li>
          ))}
        </ol>
        <Button size="icon" variant="outline" onClick={() => go(stepIdx + 1)} disabled={stepIdx >= run.steps.length - 1} aria-label="Next step"><ChevronRight /></Button>
      </div>

      <div className="grid grid-cols-[minmax(0,1fr)] gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">What the agent saw</CardTitle>
            <p className="text-xs text-muted-foreground">The text, links and forms a crawler hands to the agent. No JavaScript is run.</p>
          </CardHeader>
          <CardContent className="space-y-3">
            {!view ? (
              <p className="text-sm text-muted-foreground">No view was recorded for this step.</p>
            ) : (
              <>
                <div>
                  <p className="font-medium">{view.title || "(no title)"}</p>
                  <p className="break-all font-mono text-xs text-muted-foreground">{view.url}</p>
                  <div className="mt-1 flex flex-wrap gap-1">
                    <Badge tone={view.http_status && view.http_status < 400 ? "ok" : "fail"}>HTTP {view.http_status || "error"}</Badge>
                    {view.blockers.map((b) => <Badge key={b} tone="fail">{b}</Badge>)}
                  </div>
                  {view.error && <p className="mt-1 text-sm text-fail">{view.error}</p>}
                </div>
                <div>
                  <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Page text ({view.text.length} chars)</p>
                  <pre className="max-h-40 overflow-auto whitespace-pre-wrap rounded-md border bg-muted p-3 font-mono text-xs">{view.text || "(empty: the page has no text without JavaScript)"}</pre>
                </div>
                <div>
                  <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Links the agent can open ({view.links.length})</p>
                  {view.links.length === 0 ? (
                    <p className="text-sm text-muted-foreground">None in the HTML.</p>
                  ) : (
                    <ul className="max-h-56 overflow-auto rounded-md border text-xs">
                      {view.links.map((link) => (
                        <li key={link.i} ref={(el) => { if (el && link.i === chosen) el.scrollIntoView({ block: "nearest" }); }}
                          className={cn("flex gap-2 border-b px-2 py-1 last:border-0", link.i === chosen && "bg-primary/10 font-medium")}>
                          <span className="w-6 shrink-0 text-right font-mono text-muted-foreground">{link.i}</span>
                          <span className="min-w-0 flex-1 truncate">{link.text || "(no text)"} <span className="font-mono text-muted-foreground">{path(link.url)}</span></span>
                          {link.i === chosen && <Badge tone="primary">chosen</Badge>}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
                {view.forms.length > 0 && (
                  <div>
                    <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Forms ({view.forms.length})</p>
                    {view.forms.map((form, i) => (
                      <p key={i} className="text-xs text-muted-foreground">{form.method.toUpperCase()}: {form.fields.map((field) => field.label || field.name || field.type).join(", ")}</p>
                    ))}
                  </div>
                )}
              </>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div className="flex items-center justify-between gap-2">
              <CardTitle className="text-base">The same page without JavaScript</CardTitle>
              {pageUrl && (
                <Button size="sm" variant="outline" onClick={() => setShowPage((v) => !v)}>
                  {showPage ? <EyeOff /> : <Eye />}{showPage ? "Hide" : "Show the page"}
                </Button>
              )}
            </div>
            <p className="text-xs text-muted-foreground">Shown inert: scripts, frames and forms are removed and the sandbox blocks anything from running.</p>
          </CardHeader>
          <CardContent>
            {showPage && pageUrl ? (
              <iframe key={pageUrl} title={`Page ${view?.url} without JavaScript`} src={pageUrl} sandbox="" referrerPolicy="no-referrer" loading="lazy"
                className="h-[28rem] w-full rounded-md border bg-white" />
            ) : (
              <p className="rounded-md border border-dashed p-6 text-center text-sm text-muted-foreground">
                {pageUrl ? "Hidden. Show it to compare what a person sees with what the agent received." : "This step has no page to show."}
              </p>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardContent className="space-y-1 pt-5">
          {step.action === "finish" ? (
            <AnswerSummary answer={run.answer as Record<string, unknown> | null} />
          ) : next ? (
            <>
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Then the agent</p>
              <p className="text-sm"><b>{ACTION_TEXT[next.action] ?? next.action}</b>{next.target && next.target !== "back" ? <> <span className="font-mono text-xs text-muted-foreground">{next.target.startsWith("http") ? path(next.target) : next.target}</span></> : null}</p>
              {next.thought && <p className="text-sm text-muted-foreground">“{next.thought}”</p>}
              {next.error && <p className="text-sm text-fail">The action failed: {next.error}</p>}
            </>
          ) : (
            <p className="text-sm text-muted-foreground">The run stopped here: {run.stop_reason}.</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
