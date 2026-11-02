"use client";

import { useEffect, useId, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, ArrowRight, BookOpen, Database, Download, FileArchive, FileCheck2, FileText, Folder, GitBranch, Layers3, Plus, RotateCcw, Save, Trash2, X } from "lucide-react";
import { api } from "@/lib/api";
import type { Artifact, Job } from "@/lib/types";
import { formatBytes } from "@/lib/utils";
import { Button } from "./ui/button";
import { Card, CardContent, CardHeader } from "./ui/card";
import { EDCSourceReviewEditor, type EDCSourceSpecificationDraft } from "./edc-source-review-editor";
import { SDTMDomainMappingReview, SDTMVariableMappingReview, type SDTMDomainMappingPlanDraft, type SDTMVariableMappingPlanDraft } from "./sdtm-mapping-stage-review";
import { SDTMReviewEditor, type SDTMPlanDraft } from "./sdtm-review-editor";
import { TLFInventoryReview, TLFJsonEditor, TLFProgrammingReview, TLFShellReview, TLFTableOfContents, TLFReviewEditor, type TLFAnalysisPlanDraft, type TLFInventoryPlanDraft, type TLFPlanDraft } from "./tlf-review-editor";
import { StatusBadge } from "./status-badge";
import { RevisionDecisionPanel } from "./revision-decision-panel";
import { useReviewDraft } from "@/lib/review-draft-context";
import { ReviewPatchPanel } from "./review-patch-panel";

export function ResultView({ job, onReset }: { job: Job; onReset: () => void }) {
  const isSdtmDomainRerun = job.workflow === "sdtm" && (
    job.review_stage === "domain_mapping_completed" || job.review_stage === "variable_mapping_domain" || job.review_stage === "rule_augmentation_domain"
  );
  const { setCurrentResult } = useReviewDraft();
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
    if (job.status !== "review_required") { setCurrentResult(null); return; }
    setCurrentResult(job.workflow === "tlf" ? tlfDraft : isSdtmDomainRerun ? sdtmDraft : edcSourceDraft);
  }, [job.status, job.workflow, edcSourceDraft, isSdtmDomainRerun, sdtmDraft, tlfDraft, setCurrentResult]);
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
  const reopenDomainMutation = useMutation({
    mutationFn: () => api.reopenSdtmDomainMapping(job.id),
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
        <div role="group" aria-label="Generation result controls" className="flex shrink-0 items-center gap-2">
          <StatusBadge status={job.status} />
          <ResultHeaderAction
            label="New generation"
            description="Open a blank form for a separate generation with newly selected inputs. This job stays in history and keeps running if it is currently active."
            icon={<Plus size={16} />}
            onClick={onReset}
          />
          {job.status !== "queued" && job.status !== "running" && <ResultHeaderAction
            label="Retry same inputs"
            description={job.workflow === "sdtm"
              ? "Reuse this job's uploaded inputs and approved SDTM stages, then resume from the earliest incomplete stage. A valid saved plan may be rebuilt without another model call."
              : "Reuse this job's uploaded inputs and options, clear its current result artifacts, and queue the same job again."}
            icon={<RotateCcw size={16} />}
            onClick={() => retryMutation.mutate()}
            disabled={retryMutation.isPending}
          />}
          <ResultHeaderAction
            label="Delete job permanently"
            description="Permanently delete this job, its stored inputs, generated artifacts, and recorded history. This action cannot be undone."
            icon={<Trash2 size={16} />}
            onClick={() => deleteMutation.mutate()}
            disabled={deleteMutation.isPending}
            danger
          />
        </div>
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
            {job.review_patch && <ReviewPatchPanel job={job} summaryOnly={job.workflow === "sdtm" && (isSdtmDomainRerun || job.review_stage === "domain_mapping" || job.review_stage === "variable_mapping")} />}
            <div>{job.workflow === "tlf" ? (job.review_stage === "tlf_inventory" ? <TLFInventoryReview value={tlfDraft} onChange={(next) => setTlfDraft(next)} onApprove={(next: TLFInventoryPlanDraft) => approveTlfInventoryMutation.mutate(next)} saving={approveTlfInventoryMutation.isPending} error={approveTlfInventoryMutation.error?.message} /> : job.review_stage === "tlf_programming" ? <TLFProgrammingReview value={tlfDraft} onChange={(next) => setTlfDraft(next)} onApprove={(next: TLFPlanDraft) => approveTlfProgrammingMutation.mutate(next)} saving={approveTlfProgrammingMutation.isPending} error={approveTlfProgrammingMutation.error?.message} /> : <TLFShellReview value={tlfDraft} onChange={(next) => setTlfDraft(next)} onApprove={(next: TLFAnalysisPlanDraft) => approveTlfShellMutation.mutate(next)} saving={approveTlfShellMutation.isPending} error={approveTlfShellMutation.error?.message} />) : isSdtmDomainRerun ? <SDTMReviewEditor jobId={job.id} workbench={job.sdtm_workbench} value={sdtmDraft} artifacts={job.artifacts} onChange={(next) => setSdtmDraft(next)} onSave={(next) => updateMutation.mutate(next)} saving={updateMutation.isPending} error={updateMutation.error?.message} reviewJob={job} feedbackEvents={agentQuery.data?.events} initialStage={job.review_stage === "domain_mapping_completed" ? "domains" : job.review_stage === "variable_mapping_domain" ? "variables" : "rules"} /> : job.review_stage === "domain_mapping" ? <SDTMDomainMappingReview value={edcSourceDraft} onChange={(next) => setEdcSourceDraft(next)} onApprove={(next: SDTMDomainMappingPlanDraft) => approveDomainMutation.mutate(next)} saving={approveDomainMutation.isPending} error={approveDomainMutation.error?.message} reviewJob={job} /> : job.review_stage === "variable_mapping" ? <SDTMVariableMappingReview value={edcSourceDraft} onChange={(next) => setEdcSourceDraft(next)} onApprove={(next: SDTMVariableMappingPlanDraft) => approveVariableMutation.mutate(next)} saving={approveVariableMutation.isPending} error={approveVariableMutation.error?.message} reviewJob={job} feedbackEvents={agentQuery.data?.events} onReturnToDomainMapping={() => reopenDomainMutation.mutate()} returningToDomainMapping={reopenDomainMutation.isPending} returnDomainError={reopenDomainMutation.error?.message} /> : <EDCSourceReviewEditor value={edcSourceDraft} onChange={(next) => setEdcSourceDraft(next)} onApprove={(next: EDCSourceSpecificationDraft) => approveSourceMutation.mutate(next)} saving={approveSourceMutation.isPending} error={approveSourceMutation.error?.message} />}</div>
            {!isSdtmDomainRerun && !(job.workflow === "sdtm" && job.review_stage === "variable_mapping") && <RevisionDecisionPanel result={job.result} warnings={job.warnings} events={agentQuery.data?.events} />}
          </div>
        ) : <><div className="flex flex-wrap gap-2 border-b border-white/10" role="tablist">
          {(["preview", ...(job.status === "succeeded" ? ["edit" as const, ...(job.workflow === "tlf" ? ["json" as const] : [])] : []), "artifacts", "warnings"] as const).map((item) => (
            <button key={item} role="tab" aria-selected={tab === item} onClick={() => setTab(item)} className={`focus-ring rounded-t-lg px-4 py-2.5 text-sm font-bold capitalize ${tab === item ? "border-b-2 border-clinical-500 text-violet-300" : "text-zinc-500 hover:text-zinc-300"}`}>{item === "edit" ? (job.workflow === "sdtm" ? "SDTM review" : job.workflow === "tlf" ? "Shell" : "Edit") : item === "json" ? "Advanced JSON" : item}</button>
          ))}
        </div>
        <div className="min-h-72 py-5">
          {tab === "preview" && (job.result ? (job.workflow === "sdtm" ? <SDTMOverview value={sdtmDraft} workbench={job.sdtm_workbench} artifacts={job.artifacts} /> : job.workflow === "tlf" ? <TLFTableOfContents value={tlfDraft} onEdit={() => setTab("edit")} /> : <StructuredPreview value={job.result} />) : <EmptyState text="A structured preview will appear when generation completes." />)}
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
            <div className="space-y-5">
              {job.workflow === "sdtm" && <SubmissionPackageTree artifact={job.artifacts.find((artifact) => artifact.name === "sdtm-submission-package.zip")} />}
              <section className="space-y-2">
                <div className="pb-1"><p className="text-sm font-extrabold text-zinc-200">Individual artifacts</p><p className="mt-1 text-xs text-zinc-500">Download standalone review files or the complete evidence bundle.</p></div>
              {job.artifacts.filter((artifact) => artifact.name !== "sdtm-submission-package.zip").map((artifact) => (
                <a key={artifact.id} href={api.artifactUrl(artifact.download_url)} className="focus-ring flex items-center justify-between rounded-xl border border-white/10 bg-white/[0.02] px-4 py-3 transition hover:border-clinical-500 hover:bg-clinical-500/[0.06]">
                  <div className="flex min-w-0 items-center gap-3"><FileText size={18} className="shrink-0 text-violet-300" /><div className="min-w-0"><p className="truncate text-sm font-bold text-zinc-200">{artifact.name}</p><p className="text-xs text-zinc-500">{formatBytes(artifact.size_bytes)}</p></div></div><Download size={17} className="text-zinc-500" />
                </a>
              ))}
              <Button asChild variant="clinical" className="mt-4"><a href={api.bundleUrl(job.id)}><FileArchive size={17} /> {job.workflow === "sdtm" ? "Download audit evidence bundle" : "Download complete bundle"}</a></Button>
              </section>
            </div>
          ) : <EmptyState text="Downloads will appear after successful generation." />)}
          {tab === "warnings" && (job.warnings.length ? <ul className="space-y-2">{job.warnings.map((warning, index) => <li className="rounded-lg border border-amber-500/20 bg-amber-500/[0.07] px-4 py-3 text-sm leading-6 text-amber-200" key={`${warning}-${index}`}>{warning}</li>)}</ul> : <EmptyState text="No workflow warnings have been recorded yet." />)}
        </div></>}
      </CardContent>
    </Card>
  );
}

function ResultHeaderAction({ label, description, icon, onClick, disabled = false, danger = false }: {
  label: string;
  description: string;
  icon: ReactNode;
  onClick: () => void;
  disabled?: boolean;
  danger?: boolean;
}) {
  const tooltipId = useId();
  return <div className="group/action relative">
    <Button
      type="button"
      variant={danger ? "danger" : "outline"}
      aria-label={label}
      aria-describedby={tooltipId}
      className="h-9 w-9 p-0"
      onClick={onClick}
      disabled={disabled}
    >
      {icon}
      <span className="sr-only">{label}</span>
    </Button>
    <div id={tooltipId} role="tooltip" className="pointer-events-none invisible absolute right-0 top-[calc(100%+0.5rem)] z-50 w-72 translate-y-1 rounded-lg border border-white/15 bg-[#101012] p-3 opacity-0 shadow-2xl transition duration-150 group-hover/action:visible group-hover/action:translate-y-0 group-hover/action:opacity-100 group-focus-within/action:visible group-focus-within/action:translate-y-0 group-focus-within/action:opacity-100">
      <p className="text-xs font-bold text-zinc-100">{label}</p>
      <p className="mt-1 text-[11px] leading-5 text-zinc-400">{description}</p>
    </div>
  </div>;
}

const submissionFolders = ["data", "define", "raw", "spec", "program"] as const;

export function SubmissionPackageTree({ artifact }: { artifact?: Artifact }) {
  if (!artifact) return (
    <section className="rounded-xl border border-dashed border-white/15 bg-white/[0.02] p-4">
      <p className="text-sm font-extrabold text-zinc-200">SDTM submission package</p>
      <p className="mt-1 text-xs leading-5 text-zinc-500">Rebuild the current SDTM artifacts to create the structured submission ZIP.</p>
    </section>
  );
  const members = artifact.package_members ?? [];
  const rootFiles = members.filter((member) => !member.is_directory && !member.path.includes("/"));
  return (
    <section className="overflow-hidden rounded-xl border border-violet-400/20 bg-violet-500/[0.05]">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 p-4">
        <div><p className="text-sm font-extrabold text-zinc-100">SDTM submission package</p><p className="mt-1 text-xs leading-5 text-zinc-400">The folder view mirrors the contents of the downloadable ZIP. Empty optional folders remain visible.</p></div>
        <Button asChild variant="clinical" size="sm"><a href={api.artifactUrl(artifact.download_url)}><FileArchive size={16} />Download package</a></Button>
      </header>
      <div className="grid gap-3 p-4 lg:grid-cols-2">
        {submissionFolders.map((folder) => {
          const files = members.filter((member) => !member.is_directory && member.path.startsWith(`${folder}/`));
          return (
            <div key={folder} className="min-w-0 rounded-lg border border-white/10 bg-[#111113] p-3">
              <div className="flex items-center justify-between gap-3"><div className="flex items-center gap-2"><Folder size={17} className="text-violet-300" /><p className="font-mono text-sm font-bold text-zinc-200">{folder}/</p></div><span className="rounded-full bg-white/[0.06] px-2 py-0.5 text-[10px] font-bold text-zinc-500">{files.length}</span></div>
              {files.length ? <ul className="mt-3 max-h-56 space-y-1.5 overflow-y-auto pr-1">{files.map((member) => <li key={member.path} className="flex items-center justify-between gap-3 rounded-md bg-white/[0.025] px-2.5 py-2"><span className="min-w-0 truncate font-mono text-[11px] text-zinc-300">{member.path.slice(folder.length + 1)}</span><span className="shrink-0 text-[10px] text-zinc-600">{formatBytes(member.size_bytes)}</span></li>)}</ul> : <p className="mt-3 text-xs italic text-zinc-600">No files available</p>}
            </div>
          );
        })}
      </div>
      {rootFiles.length > 0 && <div className="flex flex-wrap gap-2 border-t border-white/10 px-4 py-3">{rootFiles.map((member) => <span key={member.path} className="rounded-md bg-white/[0.04] px-2.5 py-1 font-mono text-[10px] text-zinc-400">{member.path} · {formatBytes(member.size_bytes)}</span>)}</div>}
    </section>
  );
}

const relationshipColors: Record<string, string> = {
  direct: "#8b5cf6",
  stack: "#06b6d4",
  join: "#22c55e",
  split: "#f59e0b",
  derived: "#f43f5e",
};

interface OverviewMapping { source: string; target: string; relationship: string; }
interface OverviewVariableSource { dataset: string; variable: string; role: string; }
interface OverviewVariable { name: string; label: string; mappingType: string; sources: OverviewVariableSource[]; vlmCount: number; }
interface OverviewDomain { domain: string; variableCount: number; variables: OverviewVariable[]; }

function SDTMOverview({ value, workbench, artifacts }: { value: Record<string, unknown>; workbench?: Job["sdtm_workbench"]; artifacts: Artifact[] }) {
  const mappings: OverviewMapping[] = recordArray(value.domain_mappings).map((item) => ({
    source: textValue(item.source_dataset, "Unknown source"),
    target: textValue(item.target_domain, "Unknown domain"),
    relationship: textValue(item.relationship, "direct").toLowerCase(),
  }));
  const domains: OverviewDomain[] = recordArray(value.datasets).map((item) => {
    const domainVariables = recordArray(item.variables).map((variable) => ({
      name: textValue(variable.name, "Unknown variable"),
      label: textValue(variable.label, "No label"),
      mappingType: textValue(variable.mapping_type, "unspecified"),
      sources: recordArray(variable.sources).map((source) => ({
        dataset: textValue(source.dataset, "Unknown dataset"),
        variable: textValue(source.variable, ""),
        role: textValue(source.role, "value"),
      })),
      vlmCount: Array.isArray(variable.value_level_metadata) ? variable.value_level_metadata.length : 0,
    }));
    return { domain: textValue(item.domain, "Unknown"), variableCount: domainVariables.length, variables: domainVariables };
  });
  const rawDatasets = workbench?.inputs.raw_datasets ?? [];
  const knownRows = rawDatasets.reduce((sum, dataset) => sum + (dataset.row_count ?? 0), 0);
  const variables = domains.reduce((sum, domain) => sum + domain.variableCount, 0);
  const sources = new Set(mappings.map((mapping) => mapping.source));
  const blankCrf = workbench?.inputs.blank_crf;
  const annotatedCrf = artifacts.find((artifact) => artifact.name === "annotated-crf.pdf");
  const crfValue = blankCrf ? "Supplied" : annotatedCrf ? "Generated" : "Not supplied";
  const crfDetail = blankCrf ?? (annotatedCrf ? "Annotated CRF available" : "No CRF evidence");
  const unresolved = Array.isArray(value.unresolved_mappings) ? value.unresolved_mappings.length : 0;

  return <div className="space-y-4">
    <section className="rounded-xl border border-violet-400/20 bg-violet-500/[0.05] p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div><h3 className="text-base font-extrabold text-zinc-100">SDTM mapping overview</h3><p className="mt-1 text-xs leading-5 text-zinc-400">{sources.size} source dataset{sources.size === 1 ? "" : "s"} · {domains.length} target domain{domains.length === 1 ? "" : "s"} · {variables} reviewed variables</p></div>
        <span className={`rounded-full px-2.5 py-1 text-[10px] font-black uppercase ${unresolved ? "bg-amber-500/10 text-amber-200" : "bg-emerald-500/10 text-emerald-300"}`}>{unresolved ? `${unresolved} unresolved` : "Mapping complete"}</span>
      </div>
    </section>

    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
      <OverviewFact icon={<BookOpen size={16} />} label="Study" value={textValue(value.study_name, "Not specified")} detail="Reviewed plan" />
      <OverviewFact icon={<Layers3 size={16} />} label="SDTM standard" value={textValue(value.standard, "Not specified")} detail="Mapping target" />
      <OverviewFact icon={<FileText size={16} />} label="Define standard" value={textValue(value.define_standard, "Not specified")} detail="Metadata version" />
      <OverviewFact icon={<Database size={16} />} label="Raw data" value={`${rawDatasets.length} dataset${rawDatasets.length === 1 ? "" : "s"}`} detail={rawDatasets.length ? `${knownRows.toLocaleString()} known rows` : "Execution unavailable"} />
      <OverviewFact icon={<FileCheck2 size={16} />} label="CRF / aCRF" value={crfValue} detail={crfDetail} />
    </div>

    <div className="grid gap-4 xl:grid-cols-2">
      <MappingFlowGraph mappings={mappings} domains={domains} />
      <RelationshipChart mappings={mappings} />
      <DomainVariableChart domains={domains} />
    </div>
  </div>;
}

function OverviewFact({ icon, label, value, detail }: { icon: ReactNode; label: string; value: string; detail: string }) {
  return <section className="min-w-0 rounded-xl border border-white/10 bg-white/[0.025] p-3">
    <div className="flex items-center gap-2 text-violet-300">{icon}<p className="text-[10px] font-black uppercase tracking-[0.1em] text-zinc-500">{label}</p></div>
    <p className="mt-3 truncate text-sm font-extrabold text-zinc-100" title={value}>{value}</p>
    <p className="mt-1 truncate text-[11px] text-zinc-500" title={detail}>{detail}</p>
  </section>;
}

function MappingFlowGraph({ mappings, domains }: { mappings: OverviewMapping[]; domains: OverviewDomain[] }) {
  const [selectedDomainName, setSelectedDomainName] = useState<string | null>(null);
  const visible = mappings.slice(0, 16);
  const sources = Array.from(new Set(visible.map((mapping) => mapping.source)));
  const targets = Array.from(new Set(visible.map((mapping) => mapping.target)));
  const selectedDomain = domains.find((domain) => domain.domain.toUpperCase() === selectedDomainName?.toUpperCase());
  const height = Math.max(180, Math.max(sources.length, targets.length) * 44 + 24);
  const nodeY = (index: number, count: number) => count <= 1 ? height / 2 : 24 + index * ((height - 48) / (count - 1));
  return <section className="overflow-hidden rounded-xl border border-white/10 bg-[#141416] xl:col-span-2">
    <header className="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 p-4"><div className="flex items-center gap-2"><GitBranch size={16} className="text-violet-300" /><div><p className="text-sm font-extrabold text-zinc-100">Source-to-domain flow</p><p className="mt-0.5 text-[11px] text-zinc-500">Reviewed dataset relationships leading into SDTM targets.</p></div></div><span className="rounded-full bg-violet-500/10 px-2.5 py-1 text-[10px] font-bold text-violet-200">Select a target domain for variable lineage</span></header>
    {visible.length ? <div className="overflow-x-auto p-3"><svg role="group" aria-label="Source-to-domain mapping graph" viewBox={`0 0 760 ${height}`} className="min-w-[660px] w-full" style={{ height: Math.min(height, 520) }}>
      <title>Source datasets connected to target SDTM domains</title>
      {visible.map((mapping, index) => {
        const sourceY = nodeY(sources.indexOf(mapping.source), sources.length);
        const targetY = nodeY(targets.indexOf(mapping.target), targets.length);
        return <path key={`${mapping.source}-${mapping.target}-${index}`} d={`M 190 ${sourceY} C 315 ${sourceY}, 445 ${targetY}, 570 ${targetY}`} fill="none" stroke={relationshipColors[mapping.relationship] ?? "#71717a"} strokeWidth="2.5" opacity="0.7"><title>{mapping.source} to {mapping.target}: {mapping.relationship}</title></path>;
      })}
      {sources.map((source, index) => { const y = nodeY(index, sources.length); return <g key={source}><rect x="10" y={y - 15} width="180" height="30" rx="7" fill="#202024" stroke="#3f3f46" /><text x="22" y={y + 4} fill="#d4d4d8" fontSize="11" fontFamily="ui-monospace, monospace">{shortLabel(source)}</text></g>; })}
      {targets.map((target, index) => {
        const y = nodeY(index, targets.length);
        const selected = selectedDomain?.domain.toUpperCase() === target.toUpperCase();
        return <g
          key={target}
          role="button"
          aria-label={`View ${target} variable mappings`}
          aria-pressed={selected}
          tabIndex={0}
          className="cursor-pointer outline-none"
          onClick={() => setSelectedDomainName(target)}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              setSelectedDomainName(target);
            }
          }}
        ><rect x="570" y={y - 15} width="180" height="30" rx="7" fill={selected ? "#4c1d95" : "#261d3b"} stroke={selected ? "#c4b5fd" : "#7c3aed"} strokeWidth={selected ? 2.5 : 1} /><text x="582" y={y + 4} fill="#ddd6fe" fontSize="11" fontWeight="700" fontFamily="ui-monospace, monospace">{shortLabel(target)}</text></g>;
      })}
      <text x="10" y="12" fill="#71717a" fontSize="9" fontWeight="700">SOURCE DATASETS</text><text x="570" y="12" fill="#71717a" fontSize="9" fontWeight="700">TARGET DOMAINS</text>
    </svg></div> : <ChartEmpty text="No source-to-domain mappings are available." />}
    {mappings.length > visible.length && <p className="border-t border-white/10 px-4 py-2 text-[10px] text-zinc-500">Showing the first {visible.length} of {mappings.length} relationships.</p>}
    {selectedDomain && <DomainVariableLineage domain={selectedDomain} onClose={() => setSelectedDomainName(null)} />}
  </section>;
}

function DomainVariableLineage({ domain, onClose }: { domain: OverviewDomain; onClose: () => void }) {
  const visible = domain.variables.slice(0, 30);
  return <section role="region" aria-label={`${domain.domain} variable-level mappings`} className="border-t border-violet-400/20 bg-violet-500/[0.035] p-4">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><p className="font-mono text-sm font-extrabold text-violet-200">{domain.domain} variable lineage</p><p className="mt-1 text-[11px] text-zinc-500">{domain.variableCount} reviewed target variable{domain.variableCount === 1 ? "" : "s"}; source roles and mapping types are shown below.</p></div>
      <Button type="button" variant="ghost" size="sm" aria-label={`Close ${domain.domain} variable mappings`} onClick={onClose}><X size={14} />Close</Button>
    </div>
    {visible.length ? <div className="mt-4 max-h-96 space-y-2 overflow-y-auto pr-1">{visible.map((variable) => <div key={variable.name} className="grid items-center gap-2 rounded-lg border border-white/[0.08] bg-black/15 p-3 md:grid-cols-[minmax(0,1fr)_1.5rem_minmax(0,1fr)]">
      <div className="flex min-w-0 flex-wrap gap-1.5">{variable.sources.length ? variable.sources.map((source, index) => <span key={`${source.dataset}-${source.variable}-${source.role}-${index}`} className="rounded-md border border-cyan-500/20 bg-cyan-500/[0.07] px-2 py-1 font-mono text-[10px] text-cyan-200" title={`${source.dataset}.${source.variable || "(dataset-level)"} · ${source.role}`}>{source.dataset}{source.variable ? `.${source.variable}` : ""}<span className="ml-1 text-cyan-500">· {source.role}</span></span>) : <span className="rounded-md border border-zinc-500/20 bg-zinc-500/[0.07] px-2 py-1 text-[10px] text-zinc-400">Assigned / derived</span>}</div>
      <ArrowRight size={14} className="hidden justify-self-center text-zinc-600 md:block" />
      <div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><span className="font-mono text-xs font-bold text-violet-200">{domain.domain}.{variable.name}</span><span className="rounded bg-white/[0.05] px-1.5 py-0.5 text-[9px] font-bold uppercase text-zinc-500">{variable.mappingType}</span>{variable.vlmCount > 0 && <span className="rounded bg-amber-500/10 px-1.5 py-0.5 text-[9px] font-bold text-amber-200">{variable.vlmCount} VLM</span>}</div><p className="mt-1 truncate text-[11px] text-zinc-500" title={variable.label}>{variable.label}</p></div>
    </div>)}</div> : <ChartEmpty text="This domain has no reviewed target variables." />}
    {domain.variables.length > visible.length && <p className="mt-2 text-[10px] text-zinc-500">Showing the first {visible.length} of {domain.variables.length} variables.</p>}
  </section>;
}

function RelationshipChart({ mappings }: { mappings: OverviewMapping[] }) {
  const order = ["direct", "stack", "join", "split", "derived"];
  const counts = order.map((relationship) => ({ relationship, count: mappings.filter((mapping) => mapping.relationship === relationship).length })).filter((item) => item.count > 0);
  let cursor = 0;
  const stops = counts.map(({ relationship, count }) => {
    const start = cursor;
    cursor += mappings.length ? (count / mappings.length) * 360 : 0;
    return `${relationshipColors[relationship]} ${start}deg ${cursor}deg`;
  });
  return <section className="rounded-xl border border-white/10 bg-[#141416] p-4">
    <p className="text-sm font-extrabold text-zinc-100">Mapping relationships</p><p className="mt-1 text-[11px] text-zinc-500">How source datasets contribute to target domains.</p>
    {mappings.length ? <div role="img" aria-label="Mapping relationship distribution" className="mt-4 flex flex-wrap items-center justify-center gap-6">
      <div className="relative h-36 w-36 shrink-0 rounded-full" style={{ background: `conic-gradient(${stops.join(", ")})` }}><div className="absolute inset-5 grid place-items-center rounded-full bg-[#141416] text-center"><span><strong className="block text-2xl text-zinc-100">{mappings.length}</strong><span className="text-[9px] font-bold uppercase tracking-wider text-zinc-500">Mappings</span></span></div></div>
      <ul className="min-w-40 space-y-2">{counts.map(({ relationship, count }) => <li key={relationship} className="flex items-center justify-between gap-5 text-xs"><span className="flex items-center gap-2 capitalize text-zinc-400"><span className="h-2.5 w-2.5 rounded-sm" style={{ backgroundColor: relationshipColors[relationship] }} />{relationship}</span><strong className="text-zinc-200">{count}</strong></li>)}</ul>
    </div> : <ChartEmpty text="No mapping relationships are available." />}
  </section>;
}

function DomainVariableChart({ domains }: { domains: OverviewDomain[] }) {
  const maximum = Math.max(1, ...domains.map((domain) => domain.variableCount));
  return <section className="rounded-xl border border-white/10 bg-[#141416] p-4">
    <p className="text-sm font-extrabold text-zinc-100">Variables by domain</p><p className="mt-1 text-[11px] text-zinc-500">Reviewed target-variable coverage across the SDTM plan.</p>
    {domains.length ? <div role="img" aria-label="Reviewed variables by SDTM domain" className="mt-4 max-h-56 space-y-2.5 overflow-y-auto pr-1">{domains.map((domain) => <div key={domain.domain} className="grid grid-cols-[3rem_minmax(0,1fr)_2.5rem] items-center gap-2"><span className="font-mono text-[11px] font-bold text-violet-200">{domain.domain}</span><div className="h-2.5 overflow-hidden rounded-full bg-white/[0.06]"><div className="h-full rounded-full bg-gradient-to-r from-violet-600 to-cyan-400" style={{ width: `${domain.variableCount ? Math.max(6, (domain.variableCount / maximum) * 100) : 0}%` }} /></div><span className="text-right text-[11px] font-bold text-zinc-400">{domain.variableCount}</span></div>)}</div> : <ChartEmpty text="No target domains are available." />}
  </section>;
}

function ChartEmpty({ text }: { text: string }) { return <p className="mt-4 rounded-lg border border-dashed border-white/10 p-5 text-center text-xs text-zinc-600">{text}</p>; }
function recordArray(value: unknown): Record<string, unknown>[] { return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item)) : []; }
function textValue(value: unknown, fallback: string): string { return typeof value === "string" && value.trim() ? value : fallback; }
function shortLabel(value: string): string { return value.length > 23 ? `${value.slice(0, 21)}…` : value; }

function StructuredPreview({ value, depth = 0 }: { value: unknown; depth?: number }) {
  if (value === null || value === undefined) return <span className="text-zinc-600">Not specified</span>;
  if (Array.isArray(value)) return <div className="space-y-2">{value.map((item, index) => <div key={index} className="rounded-lg border border-white/[0.08] bg-white/[0.025] p-3"><StructuredPreview value={item} depth={depth + 1} /></div>)}</div>;
  if (typeof value === "object") return <dl className={depth ? "space-y-3" : "grid gap-4 md:grid-cols-2"}>{Object.entries(value as Record<string, unknown>).map(([key, item]) => <div key={key} className={depth ? "" : "rounded-xl border border-white/10 bg-white/[0.02] p-4"}><dt className="mb-1 text-[11px] font-black uppercase tracking-[0.12em] text-violet-300">{key.replaceAll("_", " ")}</dt><dd className="text-sm leading-6 text-zinc-300"><StructuredPreview value={item} depth={depth + 1} /></dd></div>)}</dl>;
  if (typeof value === "boolean") return <span>{value ? "Yes" : "No"}</span>;
  return <span className="whitespace-pre-wrap">{String(value)}</span>;
}

function EmptyState({ text }: { text: string }) { return <div className="grid min-h-64 place-items-center rounded-xl border border-dashed border-white/15 bg-white/[0.02] text-center text-sm text-zinc-500">{text}</div>; }

function asRecord(value: unknown): Record<string, unknown> { return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {}; }
