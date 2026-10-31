"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, Download, FileArchive, FileText, RotateCcw, Save, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import type { Job } from "@/lib/types";
import { formatBytes } from "@/lib/utils";
import { Button } from "./ui/button";
import { Card, CardContent, CardHeader } from "./ui/card";
import { EDCSourceReviewEditor, type EDCSourceSpecificationDraft } from "./edc-source-review-editor";
import { SDTMDomainMappingReview, SDTMVariableMappingReview, type SDTMDomainMappingPlanDraft, type SDTMVariableMappingPlanDraft } from "./sdtm-mapping-stage-review";
import { SDTMReviewEditor, type SDTMPlanDraft } from "./sdtm-review-editor";
import { TLFInventoryReview, TLFJsonEditor, TLFProgrammingReview, TLFShellReview, TLFTableOfContents, TLFReviewEditor, type TLFAnalysisPlanDraft, type TLFInventoryPlanDraft, type TLFPlanDraft } from "./tlf-review-editor";
import { StatusBadge } from "./status-badge";
import { RevisionDecisionPanel } from "./revision-decision-panel";

export function ResultView({ job, onReset }: { job: Job; onReset: () => void }) {
  const [tab, setTab] = useState<"preview" | "edit" | "json" | "artifacts" | "warnings">(
    job.workflow === "sdtm" && job.status === "succeeded" ? "edit" : "preview",
  );
  const [draft, setDraft] = useState(() => JSON.stringify(job.result, null, 2));
  const [sdtmDraft, setSdtmDraft] = useState<Record<string, unknown>>(() => asRecord(job.result));
  const [edcSourceDraft, setEdcSourceDraft] = useState<Record<string, unknown>>(() => asRecord(job.result));
  const [tlfDraft, setTlfDraft] = useState<Record<string, unknown>>(() => asRecord(job.result));
  const [draftError, setDraftError] = useState<string | null>(null);
  const client = useQueryClient();
  const agentQuery = useQuery({
    queryKey: ["agent-progress", job.id],
    queryFn: () => api.agentProgress(job.id),
    refetchInterval: job.status === "queued" || job.status === "running" ? 2_000 : false,
  });
  useEffect(() => {
    setDraft(JSON.stringify(job.result, null, 2));
    setSdtmDraft(asRecord(job.result));
    setEdcSourceDraft(asRecord(job.result));
    setTlfDraft(asRecord(job.result));
  }, [job.id, job.result]);
  useEffect(() => {
    setTab(job.workflow === "sdtm" && job.status === "succeeded" ? "edit" : "preview");
  }, [job.id]);
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
      setTab(job.workflow === "sdtm" ? "edit" : "preview");
    },
  });
  const approveSourceMutation = useMutation({
    mutationFn: (sourceSpec: Record<string, unknown>) => api.approveEdcSource(job.id, sourceSpec),
    onSuccess: (updated) => {
      client.setQueryData(["job", job.id], updated);
      client.invalidateQueries({ queryKey: ["jobs"] });
    },
  });
  const approveDomainMutation = useMutation({
    mutationFn: (mapping: Record<string, unknown>) => api.approveSdtmDomainMapping(job.id, mapping),
    onSuccess: (updated) => {
      client.setQueryData(["job", job.id], updated);
      client.invalidateQueries({ queryKey: ["jobs"] });
    },
  });
  const approveVariableMutation = useMutation({
    mutationFn: (mapping: Record<string, unknown>) => api.approveSdtmVariableMapping(job.id, mapping),
    onSuccess: (updated) => {
      client.setQueryData(["job", job.id], updated);
      client.invalidateQueries({ queryKey: ["jobs"] });
    },
  });
  const approveTlfShellMutation = useMutation({
    mutationFn: (shell: Record<string, unknown>) => api.approveTlfShell(job.id, shell),
    onSuccess: (updated) => {
      client.setQueryData(["job", job.id], updated);
      client.invalidateQueries({ queryKey: ["jobs"] });
    },
  });
  const approveTlfInventoryMutation = useMutation({
    mutationFn: (inventory: Record<string, unknown>) => api.approveTlfInventory(job.id, inventory),
    onSuccess: (updated) => {
      client.setQueryData(["job", job.id], updated);
      client.invalidateQueries({ queryKey: ["jobs"] });
    },
  });
  const approveTlfProgrammingMutation = useMutation({
    mutationFn: (programming: Record<string, unknown>) => api.approveTlfProgramming(job.id, programming),
    onSuccess: (updated) => {
      client.setQueryData(["job", job.id], updated);
      client.invalidateQueries({ queryKey: ["jobs"] });
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
      <CardHeader className="flex-row items-center justify-between gap-4 border-b border-white/10 pb-5">
        <div><p className="text-xs font-bold text-zinc-500">GENERATION RESULT</p><h2 className="mt-1 text-xl font-extrabold text-zinc-100">{job.title}</h2></div>
        <StatusBadge status={job.status} />
      </CardHeader>
      <CardContent className="pt-5">
        {job.status === "failed" && (
          <div className="mb-5 flex gap-3 rounded-xl border border-rose-500/20 bg-rose-500/10 p-4 text-sm text-rose-300"><AlertCircle size={19} className="shrink-0" /><span>{job.error}</span></div>
        )}
        {(job.status === "queued" || job.status === "running") && (
          <div className="mb-5 rounded-xl border border-blue-500/20 bg-blue-500/10 p-5">
            <div className="flex items-center gap-3"><span className="h-3 w-3 animate-pulse rounded-full bg-blue-400" /><p className="text-sm font-bold text-blue-200">{job.status === "queued" ? "Waiting to start…" : agentQuery.data?.stage ? `Stage ${agentQuery.data.stage_index ?? 1}/${agentQuery.data.stage_count ?? 1}: ${agentQuery.data.stage}` : "The specialist agent is reviewing sources, using approved tools, and validating its draft…"}</p></div>
            <p className="mt-2 pl-6 text-xs text-blue-300">{agentQuery.data ? `Turn ${agentQuery.data.turn}/${agentQuery.data.max_turns} · current-stage source chunks ${agentQuery.data.read_source_chunks.length}/${agentQuery.data.total_source_chunks}` : "You can leave this page; local history will retain the job."}</p>
          </div>
        )}
        {job.status === "review_required" ? (
          <div className="space-y-5 py-5">
            <div>{job.workflow === "tlf" ? (job.review_stage === "tlf_inventory" ? <TLFInventoryReview value={tlfDraft} onChange={(next) => setTlfDraft(next)} onApprove={(next: TLFInventoryPlanDraft) => approveTlfInventoryMutation.mutate(next)} saving={approveTlfInventoryMutation.isPending} error={approveTlfInventoryMutation.error?.message} /> : job.review_stage === "tlf_programming" ? <TLFProgrammingReview value={tlfDraft} onChange={(next) => setTlfDraft(next)} onApprove={(next: TLFPlanDraft) => approveTlfProgrammingMutation.mutate(next)} saving={approveTlfProgrammingMutation.isPending} error={approveTlfProgrammingMutation.error?.message} /> : <TLFShellReview value={tlfDraft} onChange={(next) => setTlfDraft(next)} onApprove={(next: TLFAnalysisPlanDraft) => approveTlfShellMutation.mutate(next)} saving={approveTlfShellMutation.isPending} error={approveTlfShellMutation.error?.message} />) : job.review_stage === "domain_mapping" ? <SDTMDomainMappingReview value={edcSourceDraft} onChange={(next) => setEdcSourceDraft(next)} onApprove={(next: SDTMDomainMappingPlanDraft) => approveDomainMutation.mutate(next)} saving={approveDomainMutation.isPending} error={approveDomainMutation.error?.message} /> : job.review_stage === "variable_mapping" ? <SDTMVariableMappingReview value={edcSourceDraft} onChange={(next) => setEdcSourceDraft(next)} onApprove={(next: SDTMVariableMappingPlanDraft) => approveVariableMutation.mutate(next)} saving={approveVariableMutation.isPending} error={approveVariableMutation.error?.message} /> : <EDCSourceReviewEditor value={edcSourceDraft} onChange={(next) => setEdcSourceDraft(next)} onApprove={(next: EDCSourceSpecificationDraft) => approveSourceMutation.mutate(next)} saving={approveSourceMutation.isPending} error={approveSourceMutation.error?.message} />}</div>
            <RevisionDecisionPanel result={job.result} warnings={job.warnings} events={agentQuery.data?.events} />
          </div>
        ) : <><div className="flex flex-wrap gap-2 border-b border-white/10" role="tablist">
          {(["preview", ...(job.status === "succeeded" ? ["edit" as const, ...(job.workflow === "tlf" ? ["json" as const] : [])] : []), "artifacts", "warnings"] as const).map((item) => (
            <button key={item} role="tab" aria-selected={tab === item} onClick={() => setTab(item)} className={`focus-ring rounded-t-lg px-4 py-2.5 text-sm font-bold capitalize ${tab === item ? "border-b-2 border-clinical-500 text-violet-300" : "text-zinc-500 hover:text-zinc-300"}`}>{item === "edit" ? (job.workflow === "sdtm" ? "SDTM review" : job.workflow === "tlf" ? "Shell" : "Edit") : item === "json" ? "Advanced JSON" : item}</button>
          ))}
        </div>
        <div className="min-h-72 py-5">
          {tab === "preview" && (job.result ? (job.workflow === "tlf" ? <TLFTableOfContents value={tlfDraft} onEdit={() => setTab("edit")} /> : <StructuredPreview value={job.result} />) : <EmptyState text="A structured preview will appear when generation completes." />)}
          {tab === "edit" && (
            job.workflow === "sdtm" ? <SDTMReviewEditor jobId={job.id} workbench={job.sdtm_workbench} value={sdtmDraft} artifacts={job.artifacts} onChange={(next) => setSdtmDraft(next)} onSave={(next: SDTMPlanDraft) => updateMutation.mutate(next)} saving={updateMutation.isPending} error={updateMutation.error?.message} /> : job.workflow === "tlf" ? <TLFReviewEditor value={tlfDraft} onChange={(next) => setTlfDraft(next)} onSave={(next: TLFPlanDraft) => updateMutation.mutate(next)} saving={updateMutation.isPending} error={updateMutation.error?.message} /> : <div className="space-y-4">
                <div className="rounded-lg border border-blue-500/20 bg-blue-500/10 px-4 py-3 text-sm leading-6 text-blue-200">Edit the validated structured result below. Saving rebuilds DOCX, PDF, XLSX, XML, code, and ZIP artifacts without another model call.</div>
                <textarea aria-label="Editable structured result" value={draft} onChange={(event) => setDraft(event.target.value)} spellCheck={false} className="focus-ring min-h-[32rem] w-full rounded-xl border border-white/15 bg-[#0d0d0f] p-4 font-mono text-xs leading-5 text-zinc-200" />
                {(draftError || updateMutation.error) && <div className="rounded-lg border border-rose-500/20 bg-rose-500/10 p-3 text-sm text-rose-300">{draftError ?? updateMutation.error?.message}</div>}
                <Button variant="clinical" onClick={saveDraft} disabled={updateMutation.isPending}><Save size={16} />{updateMutation.isPending ? "Validating and rebuilding…" : "Save revision and rebuild artifacts"}</Button>
              </div>
          )}
          {tab === "json" && job.workflow === "tlf" && <TLFJsonEditor value={tlfDraft} onSave={(next) => updateMutation.mutate(next)} saving={updateMutation.isPending} error={updateMutation.error?.message} />}
          {tab === "artifacts" && (job.artifacts.length ? (
            <div className="space-y-2">
              {job.artifacts.map((artifact) => (
                <a key={artifact.id} href={api.artifactUrl(artifact.download_url)} className="focus-ring flex items-center justify-between rounded-xl border border-white/10 bg-white/[0.02] px-4 py-3 transition hover:border-clinical-500 hover:bg-clinical-500/[0.06]">
                  <div className="flex min-w-0 items-center gap-3"><FileText size={18} className="shrink-0 text-violet-300" /><div className="min-w-0"><p className="truncate text-sm font-bold text-zinc-200">{artifact.name}</p><p className="text-xs text-zinc-500">{formatBytes(artifact.size_bytes)}</p></div></div><Download size={17} className="text-zinc-500" />
                </a>
              ))}
              <Button asChild variant="clinical" className="mt-4"><a href={api.bundleUrl(job.id)}><FileArchive size={17} /> Download complete bundle</a></Button>
            </div>
          ) : <EmptyState text="Downloads will appear after successful generation." />)}
          {tab === "warnings" && (job.warnings.length ? <ul className="space-y-2">{job.warnings.map((warning, index) => <li className="rounded-lg border border-amber-500/20 bg-amber-500/[0.07] px-4 py-3 text-sm leading-6 text-amber-200" key={`${warning}-${index}`}>{warning}</li>)}</ul> : <EmptyState text="No workflow warnings have been recorded yet." />)}
        </div></>}
        <div className="flex flex-wrap justify-between gap-3 border-t border-white/10 pt-5">
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
  if (value === null || value === undefined) return <span className="text-zinc-600">Not specified</span>;
  if (Array.isArray(value)) return <div className="space-y-2">{value.map((item, index) => <div key={index} className="rounded-lg border border-white/[0.08] bg-white/[0.025] p-3"><StructuredPreview value={item} depth={depth + 1} /></div>)}</div>;
  if (typeof value === "object") return <dl className={depth ? "space-y-3" : "grid gap-4 md:grid-cols-2"}>{Object.entries(value as Record<string, unknown>).map(([key, item]) => <div key={key} className={depth ? "" : "rounded-xl border border-white/10 bg-white/[0.02] p-4"}><dt className="mb-1 text-[11px] font-black uppercase tracking-[0.12em] text-violet-300">{key.replaceAll("_", " ")}</dt><dd className="text-sm leading-6 text-zinc-300"><StructuredPreview value={item} depth={depth + 1} /></dd></div>)}</dl>;
  if (typeof value === "boolean") return <span>{value ? "Yes" : "No"}</span>;
  return <span className="whitespace-pre-wrap">{String(value)}</span>;
}

function EmptyState({ text }: { text: string }) { return <div className="grid min-h-64 place-items-center rounded-xl border border-dashed border-white/15 bg-white/[0.02] text-center text-sm text-zinc-500">{text}</div>; }

function asRecord(value: unknown): Record<string, unknown> { return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {}; }
