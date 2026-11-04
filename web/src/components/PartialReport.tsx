import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Check, Loader2, Lock, ShieldAlert, X } from "lucide-react";
import { api, ApiError, type PartialReport, type RobotsAgent } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

const TONE = { pass: "ok", warn: "warn", fail: "fail" } as const;

function AgentRow({ agent }: { agent: RobotsAgent }) {
  return (
    <tr className="border-b last:border-0">
      <td className="px-4 py-2 font-mono text-xs">{agent.agent}</td>
      <td className="hidden px-4 py-2 text-sm text-muted-foreground sm:table-cell">{agent.label}</td>
      <td className="px-4 py-2">
        {agent.allowed ? (
          <Badge tone="ok"><Check className="size-3" />Allowed</Badge>
        ) : (
          <Badge tone="fail"><X className="size-3" />Blocked</Badge>
        )}
      </td>
    </tr>
  );
}

function AgentTable({ title, note, agents }: { title: string; note: string; agents: RobotsAgent[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{title}</CardTitle>
        <p className="text-sm text-muted-foreground">{note}</p>
      </CardHeader>
      <CardContent className="overflow-x-auto p-0">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-left text-xs tracking-wide text-muted-foreground uppercase">
              <th className="px-4 py-2 font-medium">Agent</th>
              <th className="hidden px-4 py-2 font-medium sm:table-cell">What it is</th>
              <th className="px-4 py-2 font-medium">robots.txt</th>
            </tr>
          </thead>
          <tbody>{agents.map((agent) => <AgentRow key={agent.agent} agent={agent} />)}</tbody>
        </table>
      </CardContent>
    </Card>
  );
}

export function PartialReportView({ domain, report }: { domain: string; report: PartialReport }) {
  const nav = useNavigate();
  const [allowed, setAllowed] = useState(false);
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { api.health().then((health) => setAllowed(health.ignore_robots_allowed !== false)).catch(() => {}); }, []);
  const robots = report.robots;
  const verdict = robots.verdict;
  const userFacing = robots.agents.filter((agent) => agent.kind === "user_facing");
  const training = robots.agents.filter((agent) => agent.kind === "training");

  async function rescan() {
    setBusy(true);
    setErr(null);
    try {
      const { scan_id } = await api.createScan(domain, true, true);
      nav(`/scan/${scan_id}`);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Could not start the scan.");
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <Card className="border-warn/40">
        <CardContent className="flex gap-3 pt-6">
          <Lock className="mt-0.5 size-5 shrink-0 text-warn" />
          <div className="space-y-1">
            <p className="font-medium">Partial report: robots.txt does not allow our scanner</p>
            <p className="text-sm text-muted-foreground">{report.not_evaluated}</p>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="flex flex-wrap items-start gap-3 pt-6">
          <ShieldAlert className="mt-0.5 size-5 shrink-0 text-muted-foreground" />
          <div className="min-w-0 flex-1">
            <div className="mb-1 flex items-center gap-2">
              <span className="font-medium">What robots.txt says about AI agents</span>
              <Badge tone={TONE[verdict.status as keyof typeof TONE] ?? "neutral"}>{verdict.status}</Badge>
            </div>
            <p className="text-sm">{verdict.summary}</p>
            <p className="mt-2 text-sm text-muted-foreground">
              Any agent not named in the file follows its catch-all rule, which {robots.unlisted_agents_allowed ? "allows" : "blocks"} it.
              This scanner ({robots.scanner.agent}) is {robots.scanner.allowed ? "allowed" : "not allowed"}.
            </p>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <AgentTable title="Agents that answer a person's question" note="Search and on-demand fetchers. Blocking them keeps the site out of AI answers." agents={userFacing} />
        <AgentTable title="Crawlers that collect content for models" note="Blocking these is a policy choice about training, not about being found." agents={training} />
      </div>

      {allowed && (
        <Card>
          <CardHeader><CardTitle className="text-base">Scan it anyway</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            <p className="text-sm text-muted-foreground">
              robots.txt tells crawlers what the site owner wants. Ignoring it is appropriate only for a site you own or are allowed to audit.
              The scan stays read-only and polite (same pace and page limit) and the report says that robots.txt was ignored.
            </p>
            <label className="flex items-start gap-2 text-sm">
              <input type="checkbox" className="mt-1" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
              I own this site or have permission to scan it.
            </label>
            {err && <p role="alert" className="text-sm text-fail">{err}</p>}
            <Button disabled={!consent || busy} onClick={rescan}>
              {busy && <Loader2 className="animate-spin" />}Scan ignoring robots.txt
            </Button>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
