import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Check, Copy, Download, Loader2, Mail, Sparkles, X } from "lucide-react";
import { api, ApiError, modelName, type ExportFile, type Fix, type Scan } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

const TYPE_LABEL = { jsonld: "JSON-LD", llms_txt: "llms.txt", robots_txt: "robots.txt" } as const;

function FixCard({ fix, onChange }: { fix: Fix; onChange: (updated: Fix) => void }) {
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const blocked = fix.errors.length > 0;
  async function act(call: (id: number) => Promise<Fix>, failText: string) {
    setBusy(true);
    setErr(null);
    try {
      onChange(await call(fix.id));
    } catch (error) {
      setErr(error instanceof ApiError ? error.message : failText);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Card>
      <CardHeader className="flex-row flex-wrap items-start justify-between gap-3">
        <div>
          <div className="mb-1 flex items-center gap-2">
            <Badge tone="outline">{TYPE_LABEL[fix.type]}</Badge>
            <Badge tone={fix.status === "proposed" ? "primary" : fix.status === "rejected" ? "neutral" : "ok"}>{fix.status}</Badge>
          </div>
          <CardTitle className="text-base">{fix.title}</CardTitle>
          <p className="mt-1 break-all font-mono text-xs text-muted-foreground">{fix.target_url}</p>
        </div>
        <div className="text-right">
          <p className="text-2xl font-bold tabular-nums text-ok">+{fix.est_gain}</p>
          <p className="text-xs text-muted-foreground">estimated points</p>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm text-muted-foreground">{fix.placement}</p>
        {fix.assumptions.length > 0 && (
          <div>
            <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-warn">Please verify</p>
            <ul className="list-disc space-y-0.5 pl-5 text-sm">{fix.assumptions.map((item) => <li key={item}>{item}</li>)}</ul>
          </div>
        )}
        {fix.todo.length > 0 && (
          <div>
            <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">You still need to add</p>
            <ul className="list-disc space-y-0.5 pl-5 text-sm">{fix.todo.map((item) => <li key={item}>{item}</li>)}</ul>
          </div>
        )}
        {blocked && (
          <div role="alert" className="rounded-md border border-fail/40 bg-fail/10 p-3 text-sm text-fail">
            Cannot be approved: {fix.errors.join("; ")}
          </div>
        )}
        <div className="relative">
          <Button
            variant="outline"
            size="sm"
            className="absolute right-2 top-2 bg-card"
            onClick={() => {
              navigator.clipboard?.writeText(fix.content);
              setCopied(true);
              setTimeout(() => setCopied(false), 1500);
            }}
          >
            {copied ? <Check /> : <Copy />}
            {copied ? "Copied" : "Copy"}
          </Button>
          <pre className="max-h-72 overflow-auto rounded-md border bg-muted p-4 pr-24 font-mono text-xs">{fix.content}</pre>
        </div>
        {err && <p role="alert" className="text-sm text-fail">{err}</p>}
        <div className="flex items-center justify-end gap-2">
          {(fix.status === "approved" || fix.status === "exported") && <Badge tone="ok"><Check className="size-3" />{fix.status === "exported" ? "Exported" : "Approved"}</Badge>}
          {fix.status === "rejected" && <Badge tone="neutral"><X className="size-3" />Rejected</Badge>}
          {fix.status !== "exported" && fix.status !== "rejected" && (
            <Button variant="outline" disabled={busy} onClick={() => act(api.reject, "Reject failed")}>
              <X />Reject
            </Button>
          )}
          {(fix.status === "proposed" || fix.status === "rejected") && (
            <Button disabled={blocked || busy} onClick={() => act(api.approve, "Approval failed")}>
              <Check />{fix.status === "rejected" ? "Approve instead" : "Approve"}
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

const EMAIL_FOOTER = "Built with Meta Model API · Muse Spark by Aivexia Tech\nhttps://aivexia.ro";
const MAILTO_LIMIT = 1800; // mail clients and browsers cut longer mailto: links

function buildEmail(scan: Scan | null, fixes: Fix[], scanId: number) {
  const domain = scan?.site.domain ?? "your site";
  const list = fixes.filter((fix) => fix.status !== "rejected");
  const gain = Math.round(list.reduce((sum, fix) => sum + fix.est_gain, 0) * 10) / 10;
  const scoreLine = scan?.score ? `Current AX Score: ${Math.round(scan.score.ax_score)} (grade ${scan.score.grade})\n` : "";
  const header =
    `Hi,\n\nAn AX Scanner scan of ${domain} found ${list.length} fix${list.length === 1 ? "" : "es"} that make the site easier for AI agents to read and use. ` +
    `Publishing all of them is estimated to add up to +${gain} points.\n\n${scoreLine}Scan report: ${location.origin}/scan/${scanId}\n`;
  const steps = list.map((fix, i) =>
    `${i + 1}. ${fix.title} (${fix.type}, about +${fix.est_gain} points)\n   Where: ${fix.target_url}\n   How: ${fix.placement}` +
    (fix.assumptions.length ? `\n   Please verify:\n${fix.assumptions.map((item) => `   - ${item}`).join("\n")}` : "") +
    (fix.todo.length ? `\n   Still to add:\n${fix.todo.map((item) => `   - ${item}`).join("\n")}` : ""),
  ).join("\n\n");
  const code = list.map((fix, i) => `----- ${i + 1}. ${fix.title} -----\n${fix.content}`).join("\n\n");
  const closing = "After publishing, scan the site again to confirm the new score.\n\nThanks!";
  const subject = `AX Scanner: ${list.length} fix${list.length === 1 ? "" : "es"} to publish on ${domain}`;
  const compact = `${header}\nWhat to do:\n\n${steps}\n\nThe code for each fix is in the full text, which was copied to your clipboard. Paste it here.\n\n${closing}\n\n--\n${EMAIL_FOOTER}`;
  const full = `${header}\nWhat to do:\n\n${steps}\n\nCode to publish:\n\n${code}\n\n${closing}\n\n--\n${EMAIL_FOOTER}`;
  return { subject, compact, full, count: list.length };
}

function SendToDev({ scan, fixes, scanId }: { scan: Scan | null; fixes: Fix[]; scanId: number }) {
  const [open, setOpen] = useState(false);
  const [to, setTo] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const mail = buildEmail(scan, fixes, scanId);
  if (mail.count === 0) return null;
  const mailto = (body: string) => `mailto:${encodeURIComponent(to.trim())}?subject=${encodeURIComponent(mail.subject)}&body=${encodeURIComponent(body)}`;
  async function copyFull() {
    try { await navigator.clipboard.writeText(`Subject: ${mail.subject}\n\n${mail.full}`); return true; } catch { return false; }
  }
  async function openMailApp() {
    const whole = mailto(mail.full);
    if (whole.length <= MAILTO_LIMIT) { location.href = whole; setNote(null); return; }
    const copied = await copyFull();
    location.href = mailto(mail.compact);
    setNote(copied ? "The email app opened with the steps. The full text with the code was copied to your clipboard: paste it into the message." : "The email app opened with the steps only (the code was too long for a link). Use Copy email to get the full text.");
  }
  return (
    <>
      <Button variant="outline" onClick={() => setOpen((value) => !value)}><Mail />Send to your dev</Button>
      {open && (
        <Card className="basis-full">
          <CardHeader><CardTitle>Send to your dev</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            <label className="block text-sm">
              <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-muted-foreground">To (optional)</span>
              <input type="email" value={to} onChange={(e) => setTo(e.target.value)} placeholder="dev@yourcompany.com" className="h-9 w-full rounded-md border bg-card px-2 text-sm" />
            </label>
            <div>
              <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-muted-foreground">Subject</span>
              <p className="rounded-md border bg-muted px-3 py-2 text-sm">{mail.subject}</p>
            </div>
            <div>
              <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-muted-foreground">Message</span>
              <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded-md border bg-muted p-3 font-mono text-xs">{mail.full}</pre>
            </div>
            {note && <p role="status" className="text-sm text-muted-foreground">{note}</p>}
            <div className="flex flex-wrap justify-end gap-2">
              <Button variant="outline" onClick={async () => setNote((await copyFull()) ? "Email copied." : "Could not copy. Select the text above and copy it.")}><Copy />Copy email</Button>
              <Button onClick={openMailApp}><Mail />Open in email app</Button>
            </div>
          </CardContent>
        </Card>
      )}
    </>
  );
}

function AiPrompt({ scanId, fixes }: { scanId: number; fixes: Fix[] }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<{ prompt: string; source: string } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [model, setModel] = useState("Muse Spark");
  useEffect(() => { api.health().then((health) => setModel(modelName(health.llm_model))).catch(() => {}); }, []);
  if (!fixes.some((fix) => fix.status !== "rejected")) return null;
  async function generate() {
    setOpen(true);
    setBusy(true);
    setErr(null);
    try {
      setRes(await api.fixPrompt(scanId));
    } catch (error) {
      setErr(error instanceof ApiError ? error.message : "Could not generate the prompt");
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <Button variant="outline" onClick={generate} disabled={busy}>{busy ? <Loader2 className="animate-spin" /> : <Sparkles />}{res ? `Regenerate prompt with Meta ${model}` : `Generate prompt for fixes with Meta ${model}`}</Button>
      {open && (
        <Card className="basis-full">
          <CardHeader className="flex-row flex-wrap items-center justify-between gap-2">
            <CardTitle>Prompt for your coding assistant</CardTitle>
            {res && <Badge tone={res.source === "meta" ? "primary" : "neutral"}>{res.source === "meta" ? `Written by Meta ${model}` : "From template (model unavailable)"}</Badge>}
          </CardHeader>
          <CardContent className="space-y-3">
            {busy && !res && <p className="text-sm text-muted-foreground">Writing the prompt from this scan and its fixes...</p>}
            {err && <p role="alert" className="text-sm text-fail">{err}</p>}
            {res && (
              <>
                <p className="text-sm text-muted-foreground">Paste it into your AI coding assistant (Cursor, Copilot...) in your site's repository. It includes the site context and the code of every fix.</p>
                <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-md border bg-muted p-3 font-mono text-xs">{res.prompt}</pre>
                <div className="flex justify-end">
                  <Button onClick={() => { navigator.clipboard?.writeText(res.prompt); setCopied(true); setTimeout(() => setCopied(false), 1500); }}>
                    {copied ? <Check /> : <Copy />}{copied ? "Copied" : "Copy prompt"}
                  </Button>
                </div>
              </>
            )}
          </CardContent>
        </Card>
      )}
    </>
  );
}

function download(file: ExportFile) {
  const url = URL.createObjectURL(new Blob([file.content], { type: file.content_type }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = file.path.split("/").pop() || "file.txt";
  anchor.click();
  URL.revokeObjectURL(url);
}

export default function FixesPage() {
  const id = Number(useParams().id);
  const [fixes, setFixes] = useState<Fix[] | null>(null);
  const [total, setTotal] = useState(0);
  const [files, setFiles] = useState<ExportFile[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [scan, setScan] = useState<Scan | null>(null);

  useEffect(() => {
    api.getScan(id).then(setScan).catch(() => {});
    api.fixes(id).then((res) => { setFixes(res.fixes); setTotal(res.total_est_gain); }).catch((e) => setErr(e.message));
  }, [id]);

  if (err) return <p role="alert" className="text-fail">{err}</p>;
  if (!fixes) return <Loader2 className="mx-auto mt-20 size-6 animate-spin text-muted-foreground" />;
  const approved = fixes.filter((fix) => fix.status === "approved" || fix.status === "exported").length;
  const refresh = (updated: Fix) => {
    const next = fixes.map((fix) => (fix.id === updated.id ? updated : fix));
    setFixes(next);
    setTotal(Math.round(next.filter((fix) => fix.status !== "rejected").reduce((sum, fix) => sum + fix.est_gain, 0) * 10) / 10);
    setFiles(null);  // an export shown earlier no longer matches the approved set
  };

  return (
    <div className="space-y-6">
      <Link to={`/scan/${id}`} className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="size-4" />Back to report</Link>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Proposed fixes</h1>
          <p className="text-sm text-muted-foreground">
            {fixes.length} fixes · up to <b className="text-foreground">+{total}</b> points if all are published (estimate). Nothing is exported until you approve it.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <AiPrompt scanId={id} fixes={fixes} />
          <SendToDev scan={scan} fixes={fixes} scanId={id} />
          <Button
            disabled={approved === 0}
            onClick={async () => setFiles((await api.export(id)).files)}
          >
            <Download />Export approved ({approved})
          </Button>
        </div>
      </div>

      {files && (
        <Card>
          <CardHeader><CardTitle>Export ready</CardTitle></CardHeader>
          <CardContent className="space-y-2">
            {files.map((file) => (
              <div key={file.path} className="flex items-center justify-between rounded-md border p-2 pl-3">
                <span className="font-mono text-sm">{file.path}</span>
                <Button variant="ghost" size="sm" onClick={() => download(file)}><Download />Download</Button>
              </div>
            ))}
            <p className="pt-2 text-xs text-muted-foreground">Publish the files on your site as described in README.md, then scan again to confirm the score.</p>
          </CardContent>
        </Card>
      )}

      {fixes.length === 0 ? (
        <Card><CardContent className="pt-6 text-sm text-muted-foreground">No fixes were proposed for this scan.</CardContent></Card>
      ) : (
        fixes.map((fix) => <FixCard key={fix.id} fix={fix} onChange={refresh} />)
      )}
    </div>
  );
}
