import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ChevronLeft, ChevronRight, Loader2, Search, ShieldAlert } from "lucide-react";
import { api, type ScanSummary } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn, parseUtc } from "@/lib/utils";

const STATUS_TONE = { completed: "ok", failed: "fail", needs_confirmation: "warn" } as const;
const STATUS_TEXT: Record<string, string> = {
  queued: "Queued", classifying: "Identifying", classified: "Classified", scanning: "Scanning",
  completed: "Completed", failed: "Failed", needs_confirmation: "Needs input",
};
const gradeColor = (grade: string | null) =>
  grade === "A" || grade === "B" ? "text-ok border-ok/40 bg-ok/10" : grade === "C" ? "text-warn border-warn/40 bg-warn/10" : "text-fail border-fail/40 bg-fail/10";

function ago(iso: string) {
  const secs = (Date.now() - parseUtc(iso).getTime()) / 1000;
  if (secs < 60) return "just now";
  if (secs < 3600) return `${Math.floor(secs / 60)} min ago`;
  if (secs < 86400) return `${Math.floor(secs / 3600)} h ago`;
  return `${Math.floor(secs / 86400)} d ago`;
}

function Row({ scan }: { scan: ScanSummary }) {
  const running = !["completed", "failed", "needs_confirmation"].includes(scan.status);
  return (
    <tr className="border-b last:border-0 hover:bg-muted/40">
      <td className="px-4 py-3">
        <Link to={`/scan/${scan.id}`} className="font-medium hover:underline">{scan.domain}</Link>
        <div className="text-xs text-muted-foreground">#{scan.id}</div>
      </td>
      <td className="hidden px-4 py-3 sm:table-cell">{scan.type ? <Badge tone="primary">{scan.type}</Badge> : <span className="text-muted-foreground">-</span>}</td>
      <td className="px-4 py-3">
        {scan.ax_score != null ? (
          <div className="flex items-center gap-2">
            <span className={cn("grid size-8 place-items-center rounded-md border text-sm font-bold", gradeColor(scan.grade))}>{scan.grade}</span>
            <span className="tabular-nums">{Math.round(scan.ax_score)}</span>
            {scan.gate_applied && <ShieldAlert className="size-4 text-warn" aria-label="Grade capped by a critical failure" />}
          </div>
        ) : (
          <span className="text-muted-foreground">-</span>
        )}
      </td>
      <td className="hidden px-4 py-3 md:table-cell">
        {scan.checks ? (
          <span className="font-mono text-xs">
            <span className="text-ok">{scan.checks.pass} pass</span> · <span className="text-warn">{scan.checks.warn} warn</span> · <span className="text-fail">{scan.checks.fail} fail</span>
          </span>
        ) : (
          <span className="text-muted-foreground">-</span>
        )}
      </td>
      <td className="hidden px-4 py-3 tabular-nums md:table-cell">{scan.fixes_count || <span className="text-muted-foreground">-</span>}</td>
      <td className="px-4 py-3">
        <Badge tone={scan.partial ? "warn" : STATUS_TONE[scan.status as keyof typeof STATUS_TONE] ?? "neutral"}>
          {running && <Loader2 className="size-3 animate-spin" />}
          {scan.partial ? "Partial (robots.txt)" : STATUS_TEXT[scan.status] ?? scan.status}
        </Badge>
        {scan.error && <div className="mt-1 font-mono text-[11px] text-muted-foreground">{scan.error.code}</div>}
      </td>
      <td className="whitespace-nowrap px-4 py-3 text-xs text-muted-foreground" title={parseUtc(scan.created_at).toLocaleString()}>{ago(scan.created_at)}</td>
      <td className="px-4 py-3 text-right">
        <Button asChild variant="ghost" size="sm"><Link to={scan.status === "completed" ? `/scan/${scan.id}` : `/scan/${scan.id}`}>Open</Link></Button>
      </td>
    </tr>
  );
}

export default function HistoryPage() {
  const [items, setItems] = useState<ScanSummary[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("all");
  const [pageSize, setPageSize] = useState(25);
  const [page, setPage] = useState(0);

  useEffect(() => {
    let live = true;
    const load = () => api.listScans().then((res) => live && (setItems(res.scans), setErr(null))).catch((e) => live && setErr(e.message));
    load();
    const timer = setInterval(load, 5000);
    return () => { live = false; clearInterval(timer); };
  }, []);

  const rows = useMemo(
    () => (items ?? []).filter((scan) => scan.domain.toLowerCase().includes(q.toLowerCase()) && (status === "all" || scan.status === status)),
    [items, q, status],
  );

  const total = rows.length;
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const cur = Math.min(page, pages - 1);
  const start = cur * pageSize;
  const visible = rows.slice(start, start + pageSize);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Scan history</h1>
          <p className="text-sm text-muted-foreground">Every scan run on this server, newest first. Open one to see the full report and its fixes.</p>
        </div>
        <Button asChild><Link to="/">New scan</Link></Button>
      </div>

      <Card>
        <div className="flex flex-wrap items-center gap-2 border-b p-3">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
            <input value={q} onChange={(e) => { setQ(e.target.value); setPage(0); }} placeholder="Filter by domain" aria-label="Filter by domain" className="h-9 w-56 rounded-md border bg-card pl-8 pr-2 text-sm" />
          </div>
          <select value={status} onChange={(e) => { setStatus(e.target.value); setPage(0); }} aria-label="Filter by status" className="h-9 rounded-md border bg-card px-2 text-sm">
            <option value="all">All statuses</option>
            {Object.entries(STATUS_TEXT).map(([key, text]) => <option key={key} value={key}>{text}</option>)}
          </select>
          <span className="ml-auto text-xs text-muted-foreground">{rows.length} of {items?.length ?? 0} scans</span>
        </div>
        {err && !items ? (
          <p role="alert" className="p-6 text-sm text-fail">{err}</p>
        ) : !items ? (
          <Loader2 className="mx-auto my-12 size-5 animate-spin text-muted-foreground" />
        ) : rows.length === 0 ? (
          <p className="p-8 text-center text-sm text-muted-foreground">{items.length ? "No scans match these filters." : "No scans yet. Run your first scan."}</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-xs uppercase tracking-wide text-muted-foreground">
                  <th className="px-4 py-2 font-medium">Site</th>
                  <th className="hidden px-4 py-2 font-medium sm:table-cell">Type</th>
                  <th className="px-4 py-2 font-medium">AX Score</th>
                  <th className="hidden px-4 py-2 font-medium md:table-cell">Checks</th>
                  <th className="hidden px-4 py-2 font-medium md:table-cell">Fixes</th>
                  <th className="px-4 py-2 font-medium">Status</th>
                  <th className="px-4 py-2 font-medium">When</th>
                  <th />
                </tr>
              </thead>
              <tbody>{visible.map((scan) => <Row key={scan.id} scan={scan} />)}</tbody>
            </table>
          </div>
        )}
        {items && rows.length > 0 && (
          <div className="flex flex-wrap items-center justify-between gap-3 border-t px-4 py-3 text-xs text-muted-foreground">
            <span className="tabular-nums">{start + 1}-{Math.min(start + pageSize, total)} of {total}</span>
            <div className="flex items-center gap-2">
              <label className="flex items-center gap-1">Per page
                <select value={pageSize} onChange={(e) => { setPageSize(Number(e.target.value)); setPage(0); }} className="rounded-md border bg-background px-1.5 py-1 text-foreground">
                  {[25, 50, 100].map((size) => <option key={size} value={size}>{size}</option>)}
                </select>
              </label>
              <Button variant="ghost" size="icon" onClick={() => setPage(cur - 1)} disabled={cur === 0} aria-label="Previous page"><ChevronLeft /></Button>
              <span className="tabular-nums">{cur + 1} / {pages}</span>
              <Button variant="ghost" size="icon" onClick={() => setPage(cur + 1)} disabled={cur >= pages - 1} aria-label="Next page"><ChevronRight /></Button>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}
