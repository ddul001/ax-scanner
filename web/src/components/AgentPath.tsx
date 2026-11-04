import { useMemo, useState } from "react";
import { Bot, Brain, Flag, RotateCcw } from "lucide-react";
import type { JourneyRun, JourneyStep, Report } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/** The path each agent took, one step per page, with the reason Muse gave for the move and what the run ended with.
 *  Everything shown here was recorded during the scan; nothing is estimated. */

const ACTION: Record<string, string> = {
  start: "Opens the homepage",
  open_link: "Follows a link",
  goto: "Goes to a URL",
  back: "Goes back",
  finish: "Finishes and answers",
};
const STATUS_TONE = { pass: "ok", warn: "warn", fail: "fail", skipped: "neutral", na: "neutral" } as const;
const STOP: Record<string, string> = {
  finished: "Finished",
  max_steps: "Ran out of steps",
  timeout: "Ran out of time",
  loop: "Stopped: went in circles",
  llm_error: "Model error",
};

export function pathOf(url: string) {
  try {
    const u = new URL(url);
    return u.pathname + u.search || "/";
  } catch {
    return url;
  }
}

/** The link the agent followed to reach this step, read from the previous page's link list. */
function followed(step: JourneyStep, prev?: JourneyStep): { text: string; of: number } | null {
  const links = prev?.view?.links;
  if (!links?.length) return null;
  const match = /^link #(\d+)$/.exec(step.target);
  const hit = match ? links.find((link) => link.i === Number(match[1])) : links.find((link) => link.url === step.target);
  return hit ? { text: hit.text, of: links.length } : null;
}

const CSS = `
@keyframes ap-in { from{opacity:0;transform:translateY(8px)} to{opacity:1;transform:none} }
@media (prefers-reduced-motion: reduce){ .ap-step{animation:none!important;opacity:1!important} }
`;

export function AgentPath({ report }: { report: Report }) {
  const runs = useMemo(
    () => report.results.filter((r) => r.details?.journey?.steps?.length).map((r) => ({ result: r, run: r.details.journey as JourneyRun })),
    [report],
  );
  const [idx, setIdx] = useState(0);
  const [play, setPlay] = useState(0);
  if (!runs.length) return null;
  const { result, run } = runs[Math.min(idx, runs.length - 1)];
  const checks = result.details?.verification?.checks as Record<string, boolean> | undefined;
  const reasoned = run.steps.reduce((a, s) => a + (s.reasoning_tokens ?? 0), 0);

  return (
    <div className="space-y-4">
      <style>{CSS}</style>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="flex items-center gap-2 text-sm font-semibold"><Bot className="size-4 text-primary" />How the agent moved through the site</h3>
          <p className="mt-1 max-w-2xl text-xs text-muted-foreground">
            Each step shows the reason Muse gave with its move. The model API reports how many tokens it reasoned with, not the reasoning itself,
            so the reason is the short explanation it wrote next to its action.
          </p>
        </div>
        <Button variant="ghost" size="sm" onClick={() => setPlay((p) => p + 1)}><RotateCcw />Replay</Button>
      </div>

      {runs.length > 1 && (
        <div className="flex flex-wrap gap-2" role="tablist" aria-label="Agent tasks">
          {runs.map((entry, i) => (
            <Button key={entry.run.task_id} size="sm" variant={i === idx ? "default" : "outline"} role="tab" aria-selected={i === idx}
              onClick={() => (setIdx(i), setPlay((p) => p + 1))}>
              {entry.result.check_id}
              <Badge tone={STATUS_TONE[entry.result.status as keyof typeof STATUS_TONE] ?? "neutral"} className="ml-1">{entry.result.status}</Badge>
            </Button>
          ))}
        </div>
      )}

      <p className="text-sm"><span className="text-muted-foreground">Task:</span> {run.goal}</p>

      <ol key={`${run.task_id}-${play}`} className="relative space-y-3 border-l pl-5">
        {run.steps.map((s, i) => {
          const via = i > 0 ? followed(s, run.steps[i - 1]) : null;
          const bad = !!s.error || s.status >= 400;
          return (
            <li key={s.idx} className="ap-step relative" style={{ animation: `ap-in .4s ${i * 0.45}s both ease-out` }}>
              <span className={cn("absolute -left-[27px] top-3 grid size-4 place-items-center rounded-full border-2 bg-background text-[9px] font-bold",
                bad ? "border-fail text-fail" : "border-primary text-primary")}>{s.idx}</span>
              <div className="rounded-lg border bg-card p-3">
                <div className="flex flex-wrap items-center gap-2 text-xs">
                  <b className="text-sm">{ACTION[s.action] ?? s.action}</b>
                  {s.status > 0 && <Badge tone={bad ? "fail" : "ok"}>HTTP {s.status}</Badge>}
                  {s.reasoning_tokens != null && (
                    <span className="inline-flex items-center gap-1 text-muted-foreground" title="Tokens Muse used to reason before acting. The API reports the count, not the text.">
                      <Brain className="size-3.5" />reasoned {s.reasoning_tokens} tokens
                    </span>
                  )}
                  <span className="ml-auto text-muted-foreground tabular-nums">{s.ms} ms</span>
                </div>
                {s.thought && s.action !== "start" && (
                  <p className="mt-2 border-l-2 border-primary/50 pl-3 text-sm italic">
                    <span className="not-italic text-xs font-semibold uppercase tracking-wide text-primary">Muse's reason </span>{s.thought}
                  </p>
                )}
                {via && <p className="mt-2 text-xs text-muted-foreground">Chose the link “{via.text || "(no text)"}” out of {via.of} on the previous page.</p>}
                {s.url && (
                  <p className="mt-2 break-all text-xs">
                    <span className="text-muted-foreground">Page: </span>{s.title ? <b>{s.title} </b> : null}
                    <span className="font-mono text-muted-foreground">{pathOf(s.url)}</span>
                  </p>
                )}
                {(s.error || s.blockers.length > 0) && (
                  <p className="mt-2 flex flex-wrap gap-1 text-xs">
                    {s.error && <Badge tone="fail">{s.error.slice(0, 120)}</Badge>}
                    {s.blockers.map((b) => <Badge key={b} tone="warn">{b}</Badge>)}
                  </p>
                )}
              </div>
            </li>
          );
        })}
        <li className="ap-step relative" style={{ animation: `ap-in .4s ${run.steps.length * 0.45}s both ease-out` }}>
          <span className={cn("absolute -left-[28px] top-3 grid size-5 place-items-center rounded-full border-2 bg-background",
            result.status === "pass" ? "border-ok text-ok" : result.status === "fail" ? "border-fail text-fail" : "border-warn text-warn")}><Flag className="size-3" /></span>
          <div className="rounded-lg border-2 bg-card p-3">
            <div className="flex flex-wrap items-center gap-2">
              <b className="text-sm">Result</b>
              <Badge tone={STATUS_TONE[result.status as keyof typeof STATUS_TONE] ?? "neutral"}>{result.status}</Badge>
              <Badge tone="outline">{STOP[run.stop_reason] ?? run.stop_reason}</Badge>
              <span className="ml-auto text-xs text-muted-foreground tabular-nums">
                {run.steps.length} steps · {Math.round(run.duration_ms / 1000)} s{reasoned > 0 ? ` · ${reasoned} reasoning tokens` : ""}
              </span>
            </div>
            <p className="mt-2 text-sm">{result.summary}</p>
            {checks && (
              <p className="mt-2 flex flex-wrap gap-1 text-xs">
                {Object.entries(checks).map(([k, ok]) => <Badge key={k} tone={ok ? "ok" : "fail"}>{ok ? "✓" : "✗"} {k.replace(/_/g, " ")}</Badge>)}
                <span className="ml-1 self-center text-muted-foreground">checked against the real page</span>
              </p>
            )}
          </div>
        </li>
      </ol>
    </div>
  );
}
