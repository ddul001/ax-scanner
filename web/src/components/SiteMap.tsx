import { useMemo, useState } from "react";
import { RotateCcw } from "lucide-react";
import type { DiscoveryRow } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

/** A map of the pages the scanner looks for on this type of site.
 *  Without `rows` it is a placeholder animation: no page was found yet, only the categories we look for.
 *  With `rows` (the Discovery result of a finished scan) the same nodes show what was really found. */

type Cat = { role: string; label: string };
const W = 640, H = 380, CX = W / 2, CY = H / 2, RX = 232, RY = 132, NW = 130, NH = 40;

const SOURCE: Record<DiscoveryRow["source"], string> = { llm: "found by Muse", rules: "found by rules", both: "Muse + rules", none: "" };
const TONE: Record<DiscoveryRow["state"], { cls: string; mark: string; text: string }> = {
  found: { cls: "text-ok", mark: "✓", text: "Found" },
  rejected: { cls: "text-warn", mark: "!", text: "Muse's pick rejected" },
  external: { cls: "text-warn", mark: "↗", text: "On another domain" },
  unreadable: { cls: "text-warn", mark: "!", text: "Found, could not be read" },
  not_found: { cls: "text-fail", mark: "✗", text: "Not found" },
};

const cut = (text: string, maxLen: number) => (text.length > maxLen ? text.slice(0, maxLen - 1) + "…" : text);

function place(count: number) {
  return Array.from({ length: count }, (_, index) => {
    const angle = (-90 + (360 / count) * index) * (Math.PI / 180);
    return { x: CX + RX * Math.cos(angle), y: CY + RY * Math.sin(angle) };
  });
}

const CSS = `
@keyframes sm-seek { 0%{opacity:0;stroke-dashoffset:var(--len)} 18%{opacity:1;stroke-dashoffset:0} 80%{opacity:1;stroke-dashoffset:0} 100%{opacity:0;stroke-dashoffset:0} }
@keyframes sm-node { 0%,8%{opacity:0;transform:scale(.85)} 22%,80%{opacity:1;transform:scale(1)} 100%{opacity:0;transform:scale(1)} }
@keyframes sm-in { from{opacity:0;transform:scale(.85)} to{opacity:1;transform:scale(1)} }
@keyframes sm-draw { from{stroke-dashoffset:var(--len)} to{stroke-dashoffset:0} }
@keyframes sm-ping { 0%{r:30;opacity:.5} 100%{r:90;opacity:0} }
.sm-n{transform-box:fill-box;transform-origin:center}
@media (prefers-reduced-motion: reduce){ .sm-n,.sm-e{animation:none!important;opacity:1!important;stroke-dashoffset:0!important} .sm-ping{animation:none!important;opacity:0!important} }
`;

export function SiteMap({ domain, categories, rows, visited }: { domain: string; categories: Cat[]; rows?: DiscoveryRow[]; visited?: Set<string> }) {
  const [run, setRun] = useState(0);
  const [sel, setSel] = useState<string | null>(null);
  const resolved = !!rows;
  const cats: Cat[] = useMemo(() => (rows ? rows.map((row) => ({ role: row.role, label: row.label })) : categories), [rows, categories]);
  const pts = useMemo(() => place(cats.length), [cats.length]);
  const byRole = useMemo(() => new Map((rows ?? []).map((row) => [row.role, row])), [rows]);
  const cycle = Math.max(5, cats.length * 0.8 + 2.5); // one search cycle of the placeholder, in seconds
  const detail = sel ? byRole.get(sel) : undefined;
  const found = rows?.filter((row) => row.state === "found").length ?? 0;

  return (
    <div className="space-y-3">
      <style>{CSS}</style>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground" aria-live="polite">
          {resolved
            ? `${found} of ${cats.length} page categories found on ${domain}. Click a page to see how it was found.${visited?.size ? " A marks pages the agent opened." : ""}`
            : cats.length
              ? `Looking on ${domain} for: ${cats.map((cat) => cat.label).join(", ")}.`
              : `Reading ${domain}.`}
        </p>
        {resolved && <Button variant="ghost" size="sm" onClick={() => setRun((n) => n + 1)}><RotateCcw />Replay</Button>}
      </div>
      <svg key={run} viewBox={`0 0 ${W} ${H}`} className="h-auto w-full rounded-lg border bg-card" role="img"
        aria-label={resolved ? `Map of ${cats.length} page categories and whether each was found` : `Animation: the scanner looking for ${cats.length} page categories`}>
        {!resolved && <circle className="sm-ping text-primary" cx={CX} cy={CY} r={30} fill="none" stroke="currentColor" strokeWidth={1.5} style={{ animation: "sm-ping 2.4s ease-out infinite" }} />}
        {cats.map((cat, i) => {
          const pt = pts[i];
          const row = byRole.get(cat.role);
          const tone = row ? TONE[row.state].cls : "text-muted-foreground";
          const len = Math.hypot(pt.x - CX, pt.y - CY);
          const delay = resolved ? 0.15 + i * 0.18 : i * 0.7;
          const anim = resolved ? `sm-draw .5s ${delay}s both ease-out` : `sm-seek ${cycle}s ${delay}s infinite ease-in-out`;
          const dash = resolved && row?.state !== "found" ? "5 4" : `${len}`;
          return (
            <line key={`e-${cat.role}`} className={`sm-e ${tone}`} x1={CX} y1={CY} x2={pt.x} y2={pt.y} stroke="currentColor"
              strokeWidth={resolved ? 1.6 : 1.2} strokeOpacity={resolved ? 0.7 : 0.55}
              style={{ ["--len" as string]: len, strokeDasharray: dash, animation: anim }} />
          );
        })}
        <g>
          <rect x={CX - 52} y={CY - 20} width={104} height={40} rx={10} className="fill-primary" />
          <text x={CX} y={CY - 2} textAnchor="middle" className="fill-primary-foreground" fontSize={12} fontWeight={600}>Home</text>
          <text x={CX} y={CY + 12} textAnchor="middle" className="fill-primary-foreground" fontSize={9} opacity={0.85}>{cut(domain, 20)}</text>
        </g>
        {cats.map((cat, i) => {
          const pt = pts[i];
          const row = byRole.get(cat.role);
          const tone = row ? TONE[row.state] : null;
          const delay = resolved ? 0.3 + i * 0.18 : i * 0.7;
          const anim = resolved ? `sm-in .35s ${delay}s both ease-out` : `sm-node ${cycle}s ${delay}s infinite ease-in-out`;
          const toggle = () => row && setSel(sel === cat.role ? null : cat.role);
          return (
            <g key={cat.role} className={`sm-n ${tone?.cls ?? "text-muted-foreground"}`} style={{ animation: anim, cursor: row ? "pointer" : "default" }}
              onClick={toggle} tabIndex={row ? 0 : -1} role={row ? "button" : undefined} aria-label={row ? `${cat.label}: ${tone!.text}` : undefined}
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); } }}>
              <title>{row ? `${cat.label}: ${tone!.text}` : cat.label}</title>
              <rect x={pt.x - NW / 2} y={pt.y - NH / 2} width={NW} height={NH} rx={9} className="fill-card" stroke="currentColor"
                strokeWidth={sel === cat.role ? 2.4 : 1.4} strokeDasharray={resolved ? undefined : "4 3"} />
              <text x={pt.x} y={pt.y + (row ? -3 : 4)} textAnchor="middle" fontSize={11} fontWeight={600} className="fill-foreground">{cut((tone ? tone.mark + " " : "") + cat.label, 22)}</text>
              {visited?.has(cat.role) && (
                <g><title>The agent opened this page</title>
                  <circle cx={pt.x + NW / 2 - 4} cy={pt.y - NH / 2 + 4} r={8} className="fill-primary" />
                  <text x={pt.x + NW / 2 - 4} y={pt.y - NH / 2 + 7.5} textAnchor="middle" fontSize={9} fontWeight={700} className="fill-primary-foreground">A</text></g>
              )}
              {row && <text x={pt.x} y={pt.y + 11} textAnchor="middle" fontSize={9} className="fill-muted-foreground">{SOURCE[row.source] || tone!.text}</text>}
            </g>
          );
        })}
      </svg>
      {detail && (
        <div className="rounded-md border bg-muted/40 p-3 text-sm">
          <div className="mb-1 flex flex-wrap items-center gap-2">
            <b>{detail.label}</b>
            <Badge tone={detail.state === "found" ? "ok" : detail.state === "not_found" ? "fail" : "warn"}>{TONE[detail.state].text}</Badge>
            {SOURCE[detail.source] && <Badge tone="outline">{SOURCE[detail.source]}</Badge>}
          </div>
          <p className="text-muted-foreground">{detail.how}</p>
          {detail.reason && <p className="mt-1 text-muted-foreground">Muse's reason: {detail.reason}</p>}
          {detail.url && <p className="mt-1 break-all font-mono text-xs">{detail.url}</p>}
          {detail.used_by.length > 0 && <p className="mt-1 text-xs text-muted-foreground">Used by checks: {detail.used_by.join(", ")}</p>}
        </div>
      )}
    </div>
  );
}
