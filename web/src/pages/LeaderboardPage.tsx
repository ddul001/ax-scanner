import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ChevronLeft, ChevronRight, Loader2, ShieldAlert } from "lucide-react";
import { api, label, type LeaderboardEntry } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

const gradeColor = (grade: string | null) =>
  grade === "A" || grade === "B" ? "text-ok border-ok/40 bg-ok/10" : grade === "C" ? "text-warn border-warn/40 bg-warn/10" : "text-fail border-fail/40 bg-fail/10";

export default function LeaderboardPage() {
  const [rows, setRows] = useState<LeaderboardEntry[] | null>(null);
  const [version, setVersion] = useState<string>("");
  const [err, setErr] = useState<string | null>(null);
  const [pageSize, setPageSize] = useState(25);
  const [page, setPage] = useState(0);

  useEffect(() => {
    api.leaderboard().then((res) => (setRows(res.entries), setVersion(res.current_version))).catch((e) => setErr(e.message));
  }, []);

  const total = rows?.length ?? 0;
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const cur = Math.min(page, pages - 1);
  const start = cur * pageSize;
  const visible = rows?.slice(start, start + pageSize) ?? [];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Leaderboard</h1>
          <p className="text-sm text-muted-foreground">Each site is ranked by its most recent completed scan. Older scans stay in History.</p>
        </div>
        <Button asChild><Link to="/">Scan a site</Link></Button>
      </div>

      <Card>
        {err ? (
          <p role="alert" className="p-6 text-sm text-fail">{err}</p>
        ) : !rows ? (
          <Loader2 className="mx-auto my-12 size-5 animate-spin text-muted-foreground" />
        ) : rows.length === 0 ? (
          <p className="p-8 text-center text-sm text-muted-foreground">No completed scans yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-xs uppercase tracking-wide text-muted-foreground">
                  <th className="px-4 py-2 font-medium">#</th>
                  <th className="px-4 py-2 font-medium">Site</th>
                  <th className="hidden px-4 py-2 font-medium sm:table-cell">Type</th>
                  <th className="px-4 py-2 font-medium">AX Score</th>
                  <th className="hidden px-4 py-2 font-medium md:table-cell">Weakest layer</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {visible.map((row) => (
                  <tr key={row.scan_id} className="border-b last:border-0 hover:bg-muted/40">
                    <td className="px-4 py-3 font-mono text-xs text-muted-foreground">{row.rank}</td>
                    <td className="px-4 py-3">
                      <Link to={`/scan/${row.scan_id}`} className="font-medium hover:underline">{row.domain}</Link>
                      {row.outdated && <Badge tone="warn" className="ml-2" title={`Scanned with older rules (${row.scoring_version ?? "unversioned"}); current rules are ${version}. Scan again to compare.`}>outdated</Badge>}
                    </td>
                    <td className="hidden px-4 py-3 sm:table-cell">{row.type ? <Badge tone="primary">{row.type}</Badge> : "-"}</td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <span className={cn("grid size-8 place-items-center rounded-md border text-sm font-bold", gradeColor(row.grade))}>{row.grade}</span>
                        <span className="tabular-nums">{Math.round(row.ax_score)}</span>
                        {row.gate_applied && <ShieldAlert className="size-4 text-warn" aria-label="Grade capped by a critical failure" />}
                      </div>
                    </td>
                    <td className="hidden px-4 py-3 md:table-cell">
                      {row.weakest_layer ? <span>{label(row.weakest_layer)} <span className="text-muted-foreground tabular-nums">({Math.round(row.weakest_score ?? 0)})</span></span> : "-"}
                    </td>
                    <td className="px-4 py-3 text-right"><Button asChild variant="ghost" size="sm"><Link to={`/scan/${row.scan_id}`}>Open</Link></Button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {rows && rows.length > 0 && (
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
