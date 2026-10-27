"use client";

import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, Download, FileArchive, FileText, RotateCcw, Save, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import type { Job } from "@/lib/types";
import { formatBytes } from "@/lib/utils";
import { Button } from "./ui/button";
import { Card, CardContent, CardHeader } from "./ui/card";
import { StatusBadge } from "./status-badge";

export function ResultView({ job, onReset }: { job: Job; onReset: () => void }) {
  const [tab, setTab] = useState<"preview" | "edit" | "artifacts" | "warnings">("preview");
  const [draft, setDraft] = useState(() => JSON.stringify(job.result, null, 2));
  const [draftError, setDraftError] = useState<string | null>(null);
  const client = useQueryClient();
  useEffect(() => setDraft(JSON.stringify(job.result, null, 2)), [job.id, job.result]);
  const deleteMutation = useMutation({
    mutationFn: () => api.deleteJob(job.id),
    onSuccess: () => { client.invalidateQueries({ queryKey: ["jobs"] }); onReset(); },
  });
  const retryMutation = useMutation({
    mutationFn: () => api.retryJob(job.id),
    onSuccess: (retried) => {
      client.setQueryData(["job", job.id], retried);
      client.invalidateQueries({ queryKey: ["jobs"] });
    },
  });
  const updateMutation = useMutation({
    mutationFn: (result: Record<string, unknown>) => api.updateJobResult(job.id, result),
    onSuccess: (updated) => {
      client.setQueryData(["job", job.id], updated);
      client.invalidateQueries({ queryKey: ["jobs"] });
      setDraftError(null);
      setTab("preview");
    },
  });
  const saveDraft = () => {
    try {
      const parsed: unknown = JSON.parse(draft);
      if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") throw new Error("The result must be a JSON object.");
      setDraftError(null);
      updateMutation.mutate(parsed as Record<string, unknown>);
    } catch (error) {
      setDraftError(error instanceof Error ? error.message : "Enter valid JSON.");
    }
  };
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between gap-4 border-b border-slate-100 pb-5">
        <div><p className="text-xs font-bold text-slate-500">GENERATION RESULT</p><h2 className="mt-1 text-xl font-extrabold text-ink">{job.title}</h2></div>
        <StatusBadge status={job.status} />
      </CardHeader>
      <CardContent className="pt-5">
        {job.status === "failed" && (
          <div className="mb-5 flex gap-3 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800"><AlertCircle size={19} className="shrink-0" /><span>{job.error}</span></div>
        )}
        {(job.status === "queued" || job.status === "running") && (
          <div className="mb-5 rounded-xl border border-blue-200 bg-blue-50 p-5">
            <div className="flex items-center gap-3"><span className="h-3 w-3 animate-pulse rounded-full bg-blue-600" /><p className="text-sm font-bold text-blue-900">{job.status === "queued" ? "Waiting to start…" : "Meta is drafting and renderers are preparing files…"}</p></div>
            <p className="mt-2 pl-6 text-xs text-blue-700">You can leave this page; local history will retain the job.</p>
          </div>
        )}
        <div className="flex flex-wrap gap-2 border-b border-slate-200" role="tablist">
          {(["preview", ...(job.status === "succeeded" ? ["edit" as const] : []), "artifacts", "warnings"] as const).map((item) => (
            <button key={item} role="tab" aria-selected={tab === item} onClick={() => setTab(item)} className={`focus-ring rounded-t-lg px-4 py-2.5 text-sm font-bold capitalize ${tab === item ? "border-b-2 border-clinical-600 text-clinical-700" : "text-slate-500"}`}>{item}</button>
          ))}
        </div>
        <div className="min-h-72 py-5">
          {tab === "preview" && (job.result ? <StructuredPreview value={job.result} /> : <EmptyState text="A structured preview will appear when generation completes." />)}
          {tab === "edit" && (
            <div className="space-y-4">
              <div className="rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 text-sm leading-6 text-blue-900">Edit the validated structured result below. Saving rebuilds DOCX, PDF, XLSX, XML, code, and ZIP artifacts without another model call.</div>
              <textarea aria-label="Editable structured result" value={draft} onChange={(event) => setDraft(event.target.value)} spellCheck={false} className="focus-ring min-h-[32rem] w-full rounded-xl border border-slate-300 bg-slate-950 p-4 font-mono text-xs leading-5 text-slate-100" />
              {(draftError || updateMutation.error) && <div className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">{draftError ?? updateMutation.error?.message}</div>}
              <Button variant="clinical" onClick={saveDraft} disabled={updateMutation.isPending}><Save size={16} />{updateMutation.isPending ? "Validating and rebuilding…" : "Save revision and rebuild artifacts"}</Button>
            </div>
          )}
          {tab === "artifacts" && (job.artifacts.length ? (
            <div className="space-y-2">
              {job.artifacts.map((artifact) => (
                <a key={artifact.id} href={api.artifactUrl(artifact.download_url)} className="focus-ring flex items-center justify-between rounded-xl border border-slate-200 px-4 py-3 transition hover:border-clinical-500 hover:bg-clinical-50/30">
                  <div className="flex min-w-0 items-center gap-3"><FileText size={18} className="shrink-0 text-clinical-700" /><div className="min-w-0"><p className="truncate text-sm font-bold text-ink">{artifact.name}</p><p className="text-xs text-slate-500">{formatBytes(artifact.size_bytes)}</p></div></div><Download size={17} className="text-slate-500" />
                </a>
              ))}
              <Button asChild variant="clinical" className="mt-4"><a href={api.bundleUrl(job.id)}><FileArchive size={17} /> Download complete bundle</a></Button>
            </div>
          ) : <EmptyState text="Downloads will appear after successful generation." />)}
          {tab === "warnings" && (job.warnings.length ? <ul className="space-y-2">{job.warnings.map((warning, index) => <li className="rounded-lg bg-amber-50 px-4 py-3 text-sm leading-6 text-amber-900" key={`${warning}-${index}`}>{warning}</li>)}</ul> : <EmptyState text="No workflow warnings have been recorded yet." />)}
        </div>
        <div className="flex flex-wrap justify-between gap-3 border-t border-slate-100 pt-5">
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" onClick={onReset}>New generation</Button>
            {job.status !== "queued" && job.status !== "running" && <Button variant="outline" onClick={() => retryMutation.mutate()} disabled={retryMutation.isPending}><RotateCcw size={16} /> Retry same inputs</Button>}
          </div>
          <Button variant="danger" onClick={() => deleteMutation.mutate()} disabled={deleteMutation.isPending}><Trash2 size={16} /> Delete job permanently</Button>
        </div>
      </CardContent>
    </Card>
  );
}

function StructuredPreview({ value, depth = 0 }: { value: unknown; depth?: number }) {
  if (value === null || value === undefined) return <span className="text-slate-400">Not specified</span>;
  if (Array.isArray(value)) return <div className="space-y-2">{value.map((item, index) => <div key={index} className="rounded-lg border border-slate-100 bg-slate-50/70 p-3"><StructuredPreview value={item} depth={depth + 1} /></div>)}</div>;
  if (typeof value === "object") return <dl className={depth ? "space-y-3" : "grid gap-4 md:grid-cols-2"}>{Object.entries(value as Record<string, unknown>).map(([key, item]) => <div key={key} className={depth ? "" : "rounded-xl border border-slate-200 p-4"}><dt className="mb-1 text-[11px] font-black uppercase tracking-[0.12em] text-clinical-700">{key.replaceAll("_", " ")}</dt><dd className="text-sm leading-6 text-slate-700"><StructuredPreview value={item} depth={depth + 1} /></dd></div>)}</dl>;
  if (typeof value === "boolean") return <span>{value ? "Yes" : "No"}</span>;
  return <span className="whitespace-pre-wrap">{String(value)}</span>;
}

function EmptyState({ text }: { text: string }) { return <div className="grid min-h-64 place-items-center rounded-xl border border-dashed border-slate-300 bg-slate-50 text-center text-sm text-slate-500">{text}</div>; }
