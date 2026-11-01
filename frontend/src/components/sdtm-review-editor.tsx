"use client";

import { useEffect, useMemo, useState, type DragEvent, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight, BookOpen, Code2, Database, Download, FileCode2, FileScan, GripVertical, ListChecks, Play, Plus, RotateCcw, Save, ScrollText, Table2, Trash2, Upload } from "lucide-react";
import { api } from "@/lib/api";
import type { Artifact, CDISCDataset, SDTMWorkbenchState, ValidationFinding } from "@/lib/types";
import { Button } from "./ui/button";
import {
  VariableMappingMatrix,
  newSourceVariable,
  normalizeRecordPlan,
  normalizeVariable,
  vlmMatrixIssues,
  type SDTMRecordPlan,
  type SDTMVariableDraft,
} from "./sdtm-lineage-editor";

type SourceType = "raw" | "sdtm";

interface DomainMapping {
  source_dataset: string;
  source_type: SourceType;
  target_domain: string;
  relationship: "direct" | "stack" | "join" | "split" | "derived";
  rationale: string;
}

type SDTMVariable = SDTMVariableDraft;

interface SDTMDataset {
  domain: string;
  description: string;
  structure: string;
  key_variables: string[];
  record_plan: SDTMRecordPlan;
  variables: SDTMVariable[];
}

interface VariableRule {
  rule_id: string;
  target_domain: string;
  target_variable: string;
  description: string;
  logic: string;
  r_expression: string;
  sas_expression: string;
  review_notes: string[];
}

export interface SDTMPlanDraft extends Record<string, unknown> {
  study_name: string;
  standard: string;
  define_standard: string;
  domain_mappings: DomainMapping[];
  datasets: SDTMDataset[];
  rule_augmentations: VariableRule[];
  assumptions: string[];
  unresolved_mappings: string[];
}

type Stage = "domains" | "variables" | "rules" | "execution" | "acrf" | "define" | "validation" | "csdrg";

const inputClass = "focus-ring min-h-9 w-full rounded-md border border-white/10 bg-[#101012] px-2.5 py-2 text-xs text-zinc-200 placeholder:text-zinc-600";
const codeClass = "focus-ring min-h-28 w-full resize-y rounded-lg border border-white/10 bg-[#0a0a0c] p-3 font-mono text-xs leading-5 text-zinc-200 placeholder:text-zinc-700";

export function SDTMReviewEditor({ jobId, workbench, value, artifacts = [], onChange, onSave, saving, error }: {
  jobId?: string;
  workbench?: SDTMWorkbenchState | null;
  value: Record<string, unknown>;
  artifacts?: Artifact[];
  onChange: (value: SDTMPlanDraft) => void;
  onSave: (value: SDTMPlanDraft) => void;
  saving: boolean;
  error?: string | null;
}) {
  const plan = normalizePlan(value);
  const [stage, setStage] = useState<Stage>("domains");
  const [selectedDomain, setSelectedDomain] = useState(plan.datasets[0]?.domain ?? "");
  const [customSources, setCustomSources] = useState<Array<{ name: string; type: SourceType }>>([]);
  const [sourceName, setSourceName] = useState("");
  const [sourceType, setSourceType] = useState<SourceType>("raw");
  const [libraryDomain, setLibraryDomain] = useState("");
  const [libraryVersion, setLibraryVersion] = useState("3-4");
  const [libraryStandard, setLibraryStandard] = useState<"sdtm" | "sdtmig">("sdtmig");
  const [libraryBusy, setLibraryBusy] = useState(false);
  const [libraryError, setLibraryError] = useState<string | null>(null);
  const client = useQueryClient();
  const rerunMutation = useMutation({
    mutationFn: ({ stage, domain }: { stage: "variable_mapping" | "rule_augmentation"; domain: string }) =>
      api.rerunSdtmDomain(jobId!, stage, domain),
    onSuccess: (updated) => {
      client.setQueryData(["job", jobId], updated);
      client.invalidateQueries({ queryKey: ["jobs"] });
      client.invalidateQueries({ queryKey: ["agent-progress", jobId] });
    },
  });

  const sourceInventory = useMemo(() => {
    const sources = new Map<string, SourceType>();
    const variables = new Map<string, Set<string>>();
    plan.domain_mappings.forEach((mapping) => sources.set(mapping.source_dataset, mapping.source_type));
    plan.datasets.flatMap((dataset) => dataset.variables).forEach((variable) => {
      variable.sources.forEach((source) => {
        sources.set(source.dataset, sources.get(source.dataset) ?? "raw");
        const names = variables.get(source.dataset) ?? new Set<string>();
        names.add(source.variable);
        variables.set(source.dataset, names);
      });
    });
    customSources.forEach((source) => sources.set(source.name, source.type));
    return Array.from(sources, ([name, type]) => ({ name, type, variables: Array.from(variables.get(name) ?? [], (variable) => ({ name: variable })) }));
  }, [customSources, plan.datasets, plan.domain_mappings]);

  const activeDataset = plan.datasets.find((dataset) => dataset.domain === selectedDomain) ?? plan.datasets[0];
  const activeRuleDomain = activeDataset?.domain ?? "";
  const acrfArtifact = artifacts.find((artifact) => artifact.name === "annotated-crf.pdf");
  const acrfDiagnostics = artifacts.find((artifact) => artifact.name === "acrf-annotations.json");
  const defineArtifact = artifacts.find((artifact) => artifact.name === "define.xml");
  const defineHtmlArtifact = artifacts.find((artifact) => artifact.name === "define.html");
  const defineDiagnostics = artifacts.find((artifact) => artifact.name === "define-diagnostics.json");
  const csdrgJson = artifacts.find((artifact) => artifact.name === "csdrg.json");
  const csdrgPdf = artifacts.find((artifact) => artifact.name === "csdrg.pdf");
  const issues = reviewIssues(plan);

  const update = (mutate: (next: SDTMPlanDraft) => void) => {
    const next = structuredClone(plan);
    mutate(next);
    onChange(reconcilePlan(next));
  };

  const addSource = () => {
    const name = sourceName.trim();
    if (!name) return;
    setCustomSources((current) => current.some((source) => source.name === name) ? current : [...current, { name, type: sourceType }]);
    setSourceName("");
  };

  const mapSource = (sourceDataset: string, type: SourceType, targetDomain: string) => update((next) => {
    const existing = next.domain_mappings.find((mapping) => mapping.source_dataset === sourceDataset && mapping.target_domain === targetDomain);
    if (existing) {
      existing.source_type = type;
      return;
    }
    next.domain_mappings.push({
      source_dataset: sourceDataset,
      source_type: type,
      target_domain: targetDomain,
      relationship: "direct",
      rationale: "User-reviewed dataset mapping",
    });
  });

  const onDrop = (event: DragEvent, targetDomain: string) => {
    event.preventDefault();
    try {
      const source = JSON.parse(event.dataTransfer.getData("application/x-sdtm-source")) as { name: string; type: SourceType };
      if (source.name && (source.type === "raw" || source.type === "sdtm")) mapSource(source.name, source.type, targetDomain);
    } catch {
      // Ignore drops that did not originate from a source card.
    }
  };

  const importDataset = async () => {
    const domain = libraryDomain.trim().toUpperCase();
    if (!domain) return;
    setLibraryBusy(true);
    setLibraryError(null);
    try {
      const response = await api.sdtmDataset(domain, libraryVersion.trim(), libraryStandard);
      const imported = datasetFromLibrary(response, plan);
      update((next) => {
        const existing = next.datasets.find((dataset) => dataset.domain === imported.domain);
        if (existing) {
          existing.description = imported.description || existing.description;
          const names = new Set(existing.variables.map((variable) => variable.name));
          existing.variables.push(...imported.variables.filter((variable) => !names.has(variable.name)));
        } else {
          next.datasets.push(imported);
        }
        const reference = `CDISC Library reference: ${response.standard.toUpperCase()} ${response.version}, domain ${response.domain}.`;
        if (!next.assumptions.includes(reference)) next.assumptions.push(reference);
      });
      setSelectedDomain(domain);
      setLibraryDomain("");
    } catch (cause) {
      setLibraryError(cause instanceof Error ? cause.message : "Unable to retrieve the CDISC dataset.");
    } finally {
      setLibraryBusy(false);
    }
  };

  const addVariable = (domain: string) => update((next) => {
    const dataset = next.datasets.find((item) => item.domain === domain);
    if (!dataset) return;
    const source = next.domain_mappings.find((mapping) => mapping.target_domain === domain)?.source_dataset ?? "";
    dataset.variables.push(newSourceVariable(`NEW${dataset.variables.length + 1}`, source));
  });

  const addSuppQualifier = (domain: string) => update((next) => {
    const dataset = next.datasets.find((item) => item.domain === domain);
    if (!dataset) return;
    const source = next.domain_mappings.find((mapping) => mapping.target_domain === domain)?.source_dataset ?? "";
    let qval = dataset.variables.find((variable) => variable.name === "QVAL");
    if (!qval) {
      qval = newSourceVariable("QVAL", source);
      qval.label = "Data Value";
      dataset.variables.push(qval);
    }
    qval.value_level_metadata.push({
      where_clause: "QNAM = 'SPONSOR_VAR'",
      label: "Sponsor supplemental qualifier",
      data_type: "Char",
      origin: "Assigned",
      mapping_expression: "TODO: define sponsor qualifier mapping",
      sources: source ? [{ dataset: source, variable: "", role: "value" }] : [],
      controlled_terms: [],
    });
  });

  return (
    <div className="space-y-5">
      <div className="rounded-xl border border-violet-500/20 bg-violet-500/[0.06] p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div><p className="text-xs font-black uppercase tracking-[0.14em] text-violet-300">SDTM review workspace</p><p className="mt-1 text-sm text-zinc-300">Review each mapping stage, then inspect the derived aCRF and Define-XML. Saving revalidates the complete plan and rebuilds every artifact.</p></div>
          <span className="rounded-full border border-amber-500/25 bg-amber-500/10 px-3 py-1 text-[10px] font-black uppercase tracking-wider text-amber-200">Draft · review required</span>
        </div>
        {workbench && <div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">{Object.entries(workbench.lifecycle).map(([label, status]) => <div key={label} className="rounded-lg border border-white/10 bg-black/15 px-3 py-2"><p className="text-[9px] font-black uppercase tracking-wider text-zinc-500">{label.replaceAll("_", " ")}</p><p className={`mt-1 text-xs font-bold ${status === "passed" || status === "completed" || status === "ready" ? "text-emerald-300" : status === "failed" || status === "blocked" || status === "unavailable" ? "text-rose-300" : "text-amber-200"}`}>{status.replaceAll("_", " ")}</p></div>)}</div>}
      </div>

      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4" role="tablist" aria-label="SDTM review steps">
        <StageButton active={stage === "domains"} icon={<Database size={16} />} number="01" label="Domain mapping" onClick={() => setStage("domains")} />
        <StageButton active={stage === "variables"} icon={<Table2 size={16} />} number="02" label="Variable & VLM" onClick={() => setStage("variables")} />
        <StageButton active={stage === "rules"} icon={<Code2 size={16} />} number="03" label="Rule & code" onClick={() => setStage("rules")} />
        <StageButton active={stage === "execution"} icon={<Play size={16} />} number="04" label="Execution" onClick={() => setStage("execution")} />
        <StageButton active={stage === "acrf"} icon={<FileScan size={16} />} number="05" label="aCRF review" onClick={() => setStage("acrf")} />
        <StageButton active={stage === "define"} icon={<FileCode2 size={16} />} number="06" label="Define-XML" onClick={() => setStage("define")} />
        <StageButton active={stage === "validation"} icon={<ListChecks size={16} />} number="07" label="Validation" onClick={() => setStage("validation")} />
        <StageButton active={stage === "csdrg"} icon={<ScrollText size={16} />} number="08" label="cSDRG" onClick={() => setStage("csdrg")} />
      </div>

      {stage === "domains" && (
        <div className="space-y-5">
          <section className="rounded-xl border border-white/10 bg-white/[0.02] p-4">
            <div className="flex flex-wrap items-end gap-3">
              <label className="min-w-44 flex-1"><span className="mb-1.5 block text-[10px] font-black uppercase tracking-wider text-zinc-500">CDISC domain</span><input value={libraryDomain} onChange={(event) => setLibraryDomain(event.target.value.toUpperCase())} placeholder="DM, AE, SUPPDM…" className={inputClass} /></label>
              <label><span className="mb-1.5 block text-[10px] font-black uppercase tracking-wider text-zinc-500">Standard</span><select value={libraryStandard} onChange={(event) => setLibraryStandard(event.target.value as "sdtm" | "sdtmig")} className={inputClass}><option value="sdtmig">SDTMIG</option><option value="sdtm">SDTM model</option></select></label>
              <label><span className="mb-1.5 block text-[10px] font-black uppercase tracking-wider text-zinc-500">Version / product ID</span><input value={libraryVersion} onChange={(event) => setLibraryVersion(event.target.value)} className={inputClass} /></label>
              <Button type="button" variant="outline" onClick={importDataset} disabled={libraryBusy || !libraryDomain.trim()}><BookOpen size={16} />{libraryBusy ? "Loading…" : "Import from CDISC"}</Button>
            </div>
            <p className="mt-2 text-xs leading-5 text-zinc-500">Uses the configured read-only CDISC Library service. Imported standard variables are copied into this draft and can be modified; the source version remains visible in the request.</p>
            {libraryError && <p className="mt-3 rounded-lg border border-rose-500/20 bg-rose-500/10 p-3 text-xs text-rose-300">{libraryError}</p>}
          </section>

          <div className="grid gap-5 xl:grid-cols-[300px_minmax(0,1fr)]">
            <section className="rounded-xl border border-white/10 bg-[#141416] p-4">
              <p className="text-xs font-black uppercase tracking-[0.12em] text-zinc-400">Source datasets</p>
              <p className="mt-1 text-xs leading-5 text-zinc-600">Drag raw or existing SDTM datasets onto a target domain.</p>
              <div className="mt-4 space-y-2">
                {sourceInventory.map((source) => <SourceCard key={`${source.type}-${source.name}`} source={source} />)}
                {!sourceInventory.length && <p className="rounded-lg border border-dashed border-white/10 p-4 text-center text-xs text-zinc-600">Add a source dataset below.</p>}
              </div>
              <div className="mt-4 space-y-2 border-t border-white/10 pt-4">
                <input value={sourceName} onChange={(event) => setSourceName(event.target.value)} placeholder="Dataset name" className={inputClass} />
                <div className="flex gap-2"><select value={sourceType} onChange={(event) => setSourceType(event.target.value as SourceType)} className={inputClass}><option value="raw">Raw source</option><option value="sdtm">Existing SDTM</option></select><Button type="button" variant="outline" size="sm" onClick={addSource}><Plus size={14} />Add</Button></div>
              </div>
            </section>

            <section className="space-y-3">
              <RelationshipGuide />
              {plan.datasets.map((dataset) => (
                <DomainDropZone key={dataset.domain} dataset={dataset} mappings={plan.domain_mappings.filter((mapping) => mapping.target_domain === dataset.domain)} onDrop={(event) => onDrop(event, dataset.domain)} onUpdate={(mappingIndex, key, nextValue) => update((next) => {
                  const mapping = next.domain_mappings.filter((item) => item.target_domain === dataset.domain)[mappingIndex];
                  if (mapping) (mapping as unknown as Record<string, unknown>)[key] = nextValue;
                })} onRemove={(mappingIndex) => update((next) => {
                  const matching = next.domain_mappings.filter((item) => item.target_domain === dataset.domain);
                  const target = matching[mappingIndex];
                  next.domain_mappings = next.domain_mappings.filter((item) => item !== target);
                })} />
              ))}
              {!plan.datasets.length && <p className="rounded-xl border border-dashed border-white/15 p-10 text-center text-sm text-zinc-500">Import a target SDTM domain from CDISC Library to begin mapping.</p>}
            </section>
          </div>
        </div>
      )}

      {stage === "variables" && (
        <div className="space-y-4">
          <DomainTabs datasets={plan.datasets} selected={activeDataset?.domain ?? ""} onSelect={setSelectedDomain} />
          {activeDataset ? (
            <section className="overflow-hidden rounded-xl border border-white/10 bg-[#141416]">
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 p-4">
                <div><p className="text-sm font-bold text-zinc-100">{activeDataset.domain} · {activeDataset.description}</p><p className="mt-1 text-xs text-zinc-500">Use the variable-by-source matrix to edit target metadata, minor derivations, detailed lineage, and VLM rows.</p></div>
                <div className="flex flex-wrap gap-2">{jobId && <Button type="button" variant="outline" size="sm" disabled={rerunMutation.isPending} onClick={() => rerunMutation.mutate({ stage: "variable_mapping", domain: activeDataset.domain })}><RotateCcw size={14} />Rerun {activeDataset.domain} Variable &amp; VLM</Button>}<Button type="button" variant="outline" size="sm" onClick={() => addVariable(activeDataset.domain)}><Plus size={14} />Variable</Button><Button type="button" variant="outline" size="sm" onClick={() => addSuppQualifier(activeDataset.domain)}><Plus size={14} />SUPP/VLM qualifier</Button></div>
              </div>
              <div className="space-y-4 p-4">
                {jobId && <p className="rounded-lg border border-amber-400/15 bg-amber-500/[0.05] px-3 py-2 text-[11px] leading-5 text-amber-100/80">The rerun starts from the last saved approved plan, replaces only {activeDataset.domain}, refreshes its dependent rules, and requires approval before downloads change. Save any manual edits first.</p>}
                <VariableMappingMatrix variables={activeDataset.variables} inventory={sourceInventory} allowedDatasets={plan.domain_mappings.filter((mapping) => mapping.target_domain === activeDataset.domain).map((mapping) => mapping.source_dataset)} sourceRelationships={plan.domain_mappings.filter((mapping) => mapping.target_domain === activeDataset.domain).map((mapping) => ({ dataset: mapping.source_dataset, relationship: mapping.relationship }))} onChange={(variables) => update((next) => {
                  const dataset = next.datasets.find((item) => item.domain === activeDataset.domain);
                  if (!dataset) return;
                  variables.forEach((variable, index) => {
                    const previous = dataset.variables[index];
                    if (!previous || previous.name === variable.name) return;
                    const rule = next.rule_augmentations.find((item) => item.target_domain === activeDataset.domain && item.target_variable === previous.name);
                    if (rule) { rule.target_variable = variable.name; rule.rule_id = `${activeDataset.domain}-${variable.name}`; }
                  });
                  dataset.variables = variables;
                })} />
              </div>
            </section>
          ) : <EmptyReview text="Import or add an SDTM domain before reviewing variables." />}
        </div>
      )}

      {stage === "rules" && (
        <div className="space-y-5">
          <DomainTabs datasets={plan.datasets} selected={activeRuleDomain} onSelect={setSelectedDomain} />
          <section className="space-y-3">
            <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-xs font-black uppercase tracking-[0.12em] text-zinc-400">{activeRuleDomain || "Domain"} program review</p><p className="mt-1 text-xs text-zinc-600">Review the exact generated R and SAS artifacts with syntax highlighting. Programs are read-only here; rerun the domain or revise its mappings to rebuild them.</p></div>{jobId && activeRuleDomain && <Button type="button" variant="outline" size="sm" disabled={rerunMutation.isPending} onClick={() => rerunMutation.mutate({ stage: "rule_augmentation", domain: activeRuleDomain })}><RotateCcw size={14} />Rerun {activeRuleDomain} rules/code</Button>}</div>
            {activeRuleDomain ? <DomainProgramReview domain={activeRuleDomain} artifacts={artifacts} /> : <EmptyReview text="No SDTM domain is available for program review." />}
          </section>
        </div>
      )}

      {stage === "execution" && <ExecutionReview jobId={jobId} workbench={workbench} />}

      {stage === "acrf" && (
        <DerivedArtifactReview
          title="Annotated CRF review"
          description="This draft is generated from the aCRF labels in Variable & VLM. Change those labels, save the reviewed mappings, and return here to inspect the rebuilt PDF."
          artifact={acrfArtifact ?? acrfDiagnostics}
          missingMessage="No aCRF was generated because this job did not include a blank CRF PDF. Start a new generation with a blank CRF to enable annotation review."
        >
          <ACRFArtifactReview pdf={acrfArtifact} diagnostics={acrfDiagnostics} />
        </DerivedArtifactReview>
      )}

      {stage === "define" && (
        <DerivedArtifactReview
          title="Define-XML 2.1 review"
          description="This draft is generated from the reviewed domains, variables, origins, controlled terms, and value-level metadata. Update those mapping tabs and save to rebuild the XML."
          artifact={defineArtifact}
        >
          <DefineArtifactPreview xml={defineArtifact} html={defineHtmlArtifact} diagnostics={defineDiagnostics} />
        </DerivedArtifactReview>
      )}

      {stage === "validation" && <ValidationReview jobId={jobId} workbench={workbench} />}
      {stage === "csdrg" && <CSDRGReview jobId={jobId} source={csdrgJson} pdf={csdrgPdf} />}

      <div className="sticky bottom-3 z-20 flex flex-col gap-3 rounded-xl border border-white/15 bg-[#161619]/95 p-4 shadow-2xl backdrop-blur sm:flex-row sm:items-center sm:justify-between">
        <div>{issues.length ? <p className="flex items-center gap-2 text-xs font-bold text-amber-200"><AlertTriangle size={15} />{issues[0]}{issues.length > 1 ? ` (+${issues.length - 1} more)` : ""}</p> : <p className="text-xs font-bold text-emerald-300">All mapping references are ready for schema validation.</p>}{(error || rerunMutation.error) && <p className="mt-1 text-xs text-rose-300">{error ?? rerunMutation.error?.message}</p>}</div>
        <Button type="button" variant="clinical" onClick={() => onSave(plan)} disabled={saving || issues.length > 0}><Save size={16} />{saving ? "Validating and rebuilding…" : "Save reviewed mappings"}</Button>
      </div>
    </div>
  );
}

function ExecutionReview({ jobId, workbench }: { jobId?: string; workbench?: SDTMWorkbenchState | null }) {
  const client = useQueryClient();
  const [rawFiles, setRawFiles] = useState<File[]>([]);
  const query = useQuery({
    queryKey: ["sdtm-executions", jobId],
    queryFn: () => api.sdtmExecutions(jobId!),
    enabled: Boolean(jobId),
  });
  const mutation = useMutation({
    mutationFn: () => api.executeSdtm(jobId!, rawFiles),
    onSuccess: () => {
      setRawFiles([]);
      client.invalidateQueries({ queryKey: ["sdtm-executions", jobId] });
      client.invalidateQueries({ queryKey: ["job", jobId] });
    },
  });
  const repairMutation = useMutation({
    mutationFn: ({ attemptId, proposalId, approved }: { attemptId: string; proposalId: string; approved: boolean }) => api.reviewSdtmRepair(jobId!, attemptId, proposalId, approved),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["sdtm-executions", jobId] });
      client.invalidateQueries({ queryKey: ["job", jobId] });
    },
  });
  const datasets = workbench?.inputs.raw_datasets ?? [];
  return <div className="space-y-4">
    <section className="rounded-xl border border-white/10 bg-[#141416] p-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div><p className="text-sm font-extrabold text-zinc-100">Isolated R execution</p><p className="mt-1 max-w-3xl text-xs leading-5 text-zinc-500">R runs only in the dedicated network-isolated runner. SAS remains export-only. Output checks confirm readability and expected structure; they are not standards validation.</p></div>
        <span className="rounded-full border border-white/10 px-3 py-1 text-[10px] font-black uppercase tracking-wider text-zinc-300">{workbench?.lifecycle.execution?.replaceAll("_", " ") ?? "not run"}</span>
      </div>
      <div className="mt-4 grid gap-3 md:grid-cols-2">
        {datasets.map((dataset) => <div key={dataset.logical_name} className="rounded-lg border border-white/10 bg-white/[0.025] p-3"><p className="font-mono text-xs font-bold text-violet-200">{dataset.logical_name}.{dataset.format}</p><p className="mt-1 text-[11px] text-zinc-500">{dataset.row_count ?? "Unknown"} rows · {dataset.columns.length} columns · SHA-256 {dataset.sha256.slice(0, 12)}…</p></div>)}
        {!datasets.length && <p className="text-xs text-amber-200">No raw datasets were supplied. Programs are generated but cannot be executed.</p>}
      </div>
      <label className="mt-4 block rounded-lg border border-dashed border-white/15 p-3 text-xs text-zinc-400"><span className="flex items-center gap-2 font-bold text-zinc-300"><Upload size={14} />Add raw data after mapping approval</span><input className="mt-2 block w-full" type="file" accept=".csv,.xpt" multiple onChange={(event) => setRawFiles(Array.from(event.target.files ?? []))} /></label>
      <Button type="button" variant="clinical" className="mt-3" disabled={!jobId || mutation.isPending || (!datasets.length && !rawFiles.length)} onClick={() => mutation.mutate()}><Play size={15} />{mutation.isPending ? "Running in isolation…" : "Execute reviewed R"}</Button>
      {mutation.error && <p className="mt-3 text-xs text-rose-300">{mutation.error.message}</p>}
    </section>
    <section className="space-y-3">
      <p className="text-xs font-black uppercase tracking-wider text-zinc-400">Immutable attempt history</p>
      {query.data?.items.map((attempt) => <article key={attempt.attempt_id} className="rounded-xl border border-white/10 bg-[#141416] p-4">
        <div className="flex flex-wrap justify-between gap-2"><div><p className="font-mono text-xs font-bold text-violet-200">{attempt.attempt_id}</p><p className="mt-1 text-[11px] text-zinc-500">Program SHA-256 {attempt.program_hash} · exit {attempt.exit_code ?? "not available"}</p></div><span className={`rounded-full px-2 py-1 text-[10px] font-black uppercase ${attempt.status === "passed" ? "bg-emerald-500/10 text-emerald-300" : "bg-rose-500/10 text-rose-300"}`}>{attempt.status.replaceAll("_", " ")}</span></div>
        {attempt.failure_classification && <p className="mt-3 text-xs text-amber-200">Failure classification: {attempt.failure_classification.replaceAll("_", " ")}</p>}
        {attempt.repair_proposal && <div className="mt-3 rounded-lg border border-amber-500/20 bg-amber-500/[0.06] p-3"><p className="text-xs font-bold text-amber-100">Typed repair proposal · {attempt.repair_proposal.status}</p><p className="mt-1 text-xs text-zinc-300">{attempt.repair_proposal.rationale}</p><pre className="mt-2 overflow-auto rounded bg-black/30 p-2 text-[11px] text-cyan-100">{attempt.repair_proposal.diff}</pre>{attempt.repair_proposal.status === "proposed" && <div className="mt-3 flex gap-2"><Button type="button" variant="clinical" size="sm" disabled={repairMutation.isPending} onClick={() => repairMutation.mutate({ attemptId: attempt.attempt_id, proposalId: attempt.repair_proposal!.proposal_id, approved: true })}>Approve and rerun</Button><Button type="button" variant="outline" size="sm" disabled={repairMutation.isPending} onClick={() => repairMutation.mutate({ attemptId: attempt.attempt_id, proposalId: attempt.repair_proposal!.proposal_id, approved: false })}>Reject</Button></div>}</div>}
        <div className="mt-3 grid gap-2 md:grid-cols-2">{attempt.checks.map((check, index) => <div key={`${check.check_id}-${index}`} className="rounded-lg border border-white/[0.08] p-2 text-xs"><span className={check.status === "passed" ? "text-emerald-300" : check.status === "warning" ? "text-amber-300" : "text-rose-300"}>{check.status.toUpperCase()}</span><span className="ml-2 text-zinc-400">{check.message}</span></div>)}</div>
        {(attempt.stdout || attempt.stderr) && <details className="mt-3"><summary className="cursor-pointer text-xs font-bold text-zinc-400">Sanitized runner logs</summary><pre className="mt-2 max-h-64 overflow-auto rounded-lg bg-black/30 p-3 text-[11px] text-zinc-400">{[attempt.stdout, attempt.stderr].filter(Boolean).join("\n")}</pre></details>}
      </article>)}
      {!query.isPending && !query.data?.items.length && <EmptyReview text="No R execution attempts have been recorded." />}
    </section>
  </div>;
}

function ValidationReview({ jobId, workbench }: { jobId?: string; workbench?: SDTMWorkbenchState | null }) {
  const client = useQueryClient();
  const [report, setReport] = useState<File | null>(null);
  const query = useQuery({ queryKey: ["sdtm-validations", jobId], queryFn: () => api.validations(jobId!), enabled: Boolean(jobId) });
  const importMutation = useMutation({
    mutationFn: () => api.importValidation(jobId!, report),
    onSuccess: () => { setReport(null); client.invalidateQueries({ queryKey: ["sdtm-validations", jobId] }); client.invalidateQueries({ queryKey: ["job", jobId] }); },
  });
  const runMutation = useMutation({
    mutationFn: (provider: "internal" | "pinnacle21-cli") => api.runValidation(jobId!, provider),
    onSuccess: () => { client.invalidateQueries({ queryKey: ["sdtm-validations", jobId] }); client.invalidateQueries({ queryKey: ["job", jobId] }); },
  });
  return <div className="space-y-4">
    <section className="rounded-xl border border-white/10 bg-[#141416] p-4">
      <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-sm font-extrabold text-zinc-100">Provider-neutral validation review</p><p className="mt-1 max-w-3xl text-xs leading-5 text-zinc-500">Imported Pinnacle 21 reports retain their original file and provider/version provenance. Workbench checks are labeled internal. Missing CLI or Java prerequisites return unavailable, never passed.</p></div><span className="rounded-full border border-white/10 px-3 py-1 text-[10px] font-black uppercase text-zinc-300">{workbench?.lifecycle.validation?.replaceAll("_", " ") ?? "not run"}</span></div>
      <label className="mt-4 block rounded-lg border border-dashed border-white/15 p-3 text-xs text-zinc-400"><span className="font-bold text-zinc-300">Pinnacle 21 report CSV/XLSX</span><input className="mt-2 block w-full" type="file" accept=".csv,.xlsx" onChange={(event) => setReport(event.target.files?.[0] ?? null)} /></label>
      <div className="mt-3 flex flex-wrap gap-2"><Button type="button" variant="clinical" size="sm" disabled={!jobId || importMutation.isPending || (!report && !workbench?.inputs.validation_report)} onClick={() => importMutation.mutate()}>Import report</Button><Button type="button" variant="outline" size="sm" disabled={!jobId || runMutation.isPending} onClick={() => runMutation.mutate("internal")}>Run internal checks</Button><Button type="button" variant="outline" size="sm" disabled={!jobId || runMutation.isPending} onClick={() => runMutation.mutate("pinnacle21-cli")}>Run configured P21 CLI</Button></div>
      {(importMutation.error || runMutation.error) && <p className="mt-3 text-xs text-rose-300">{importMutation.error?.message ?? runMutation.error?.message}</p>}
    </section>
    {query.data?.map((record) => <section key={record.validation_id} className="rounded-xl border border-white/10 bg-[#141416] p-4"><div className="flex flex-wrap justify-between gap-2"><div><p className="text-sm font-bold text-violet-200">{record.provider}</p><p className="mt-1 text-xs text-zinc-500">Version {record.provider_version} · {record.findings.length} finding(s)</p></div><span className={`rounded-full px-2 py-1 text-[10px] font-black uppercase ${record.status === "passed" ? "bg-emerald-500/10 text-emerald-300" : record.status === "unavailable" || record.status === "failed" ? "bg-rose-500/10 text-rose-300" : "bg-amber-500/10 text-amber-300"}`}>{record.status.replaceAll("_", " ")}</span></div>{record.message && <p className="mt-3 text-xs leading-5 text-zinc-400">{record.message}</p>}{record.diagnostics?.warnings.map((warning) => <p key={warning} className="mt-2 text-xs text-amber-200">{warning}</p>)}<div className="mt-4 space-y-3">{record.findings.map((finding) => <FindingReview key={finding.finding_id} jobId={jobId} finding={finding} onSaved={() => { client.invalidateQueries({ queryKey: ["sdtm-validations", jobId] }); client.invalidateQueries({ queryKey: ["job", jobId] }); }} />)}</div></section>)}
    {!query.isPending && !query.data?.length && <EmptyReview text="Validation has not been run or imported. This is not a pass." />}
  </div>;
}

function FindingReview({ jobId, finding, onSaved }: { jobId?: string; finding: ValidationFinding; onSaved: () => void }) {
  const [status, setStatus] = useState(finding.finding_status);
  const [explanation, setExplanation] = useState(finding.explanation ?? "");
  const [approved, setApproved] = useState(Boolean(finding.approved_at));
  const mutation = useMutation({ mutationFn: () => api.updateValidationFinding(jobId!, finding.finding_id, { finding_status: status, explanation: explanation || null, disposition: explanation || null, approved, reviewer: approved ? "Workbench reviewer" : null }), onSuccess: onSaved });
  return <article className="rounded-lg border border-white/[0.08] bg-black/15 p-3"><div className="flex flex-wrap justify-between gap-2"><p className="font-mono text-xs font-bold text-zinc-200">{finding.rule_id} · {finding.dataset ?? "General"}{finding.variable ? `.${finding.variable}` : ""}</p><span className="text-[10px] font-black uppercase text-amber-300">{finding.severity}</span></div><p className="mt-2 text-xs leading-5 text-zinc-400">{finding.message}</p><div className="mt-3 grid gap-2 md:grid-cols-[180px_minmax(0,1fr)]"><select value={status} onChange={(event) => setStatus(event.target.value as ValidationFinding["finding_status"])} className={inputClass}><option value="open">Open</option><option value="accepted">Accepted</option><option value="corrected">Corrected</option><option value="not_applicable">Not applicable</option><option value="explained">Explained</option></select><textarea value={explanation} onChange={(event) => setExplanation(event.target.value)} placeholder="Reviewer disposition/explanation" className={`${inputClass} min-h-20`} /></div><div className="mt-2 flex flex-wrap items-center gap-3"><label className="flex items-center gap-2 text-xs text-zinc-300"><input type="checkbox" checked={approved} onChange={(event) => setApproved(event.target.checked)} />Approve explanation for cSDRG</label><Button type="button" variant="outline" size="sm" disabled={!jobId || mutation.isPending} onClick={() => mutation.mutate()}>Save disposition</Button>{mutation.error && <span className="text-xs text-rose-300">{mutation.error.message}</span>}</div></article>;
}

function CSDRGReview({ jobId, source, pdf }: { jobId?: string; source?: Artifact; pdf?: Artifact }) {
  const client = useQueryClient();
  const query = useQuery({ queryKey: ["csdrg-source", source?.id], queryFn: () => api.artifactText(source!.download_url), enabled: Boolean(source) });
  const [draft, setDraft] = useState("");
  useEffect(() => { if (query.data) setDraft(query.data); }, [query.data]);
  const mutation = useMutation({ mutationFn: () => { const parsed: unknown = JSON.parse(draft); if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") throw new Error("cSDRG source must be a JSON object."); return api.updateCsdrg(jobId!, parsed as Record<string, unknown>); }, onSuccess: () => { client.invalidateQueries({ queryKey: ["job", jobId] }); client.invalidateQueries({ queryKey: ["csdrg-source"] }); } });
  if (!source) return <EmptyReview text="cSDRG artifacts will appear after the SDTM plan is generated." />;
  return <div className="space-y-4"><section className="rounded-xl border border-white/10 bg-[#141416] p-4"><div className="flex flex-wrap justify-between gap-3"><div><p className="text-sm font-extrabold text-zinc-100">Editable cSDRG source</p><p className="mt-1 text-xs leading-5 text-zinc-500">Narrative sections may be edited. Execution, validation, unresolved issues, limitations, and reviewer-approved explanations remain evidence-controlled by the backend.</p></div>{pdf && <Button asChild type="button" variant="outline" size="sm"><a href={api.artifactUrl(pdf.download_url)}><Download size={14} />Download csdrg.pdf</a></Button>}</div><textarea aria-label="Editable cSDRG JSON" value={draft} onChange={(event) => setDraft(event.target.value)} className={`${codeClass} mt-4 min-h-[32rem]`} spellCheck={false} /><Button type="button" variant="clinical" className="mt-3" disabled={!jobId || mutation.isPending} onClick={() => mutation.mutate()}><Save size={15} />Save cSDRG review</Button>{mutation.error && <p className="mt-2 text-xs text-rose-300">{mutation.error.message}</p>}</section>{pdf && <iframe title="cSDRG PDF review" src={api.artifactPreviewUrl(pdf.download_url)} className="h-[48rem] w-full rounded-xl border border-white/10 bg-white" />}</div>;
}

function StageButton({ active, icon, number, label, onClick }: { active: boolean; icon: ReactNode; number: string; label: string; onClick: () => void }) {
  return <button type="button" role="tab" aria-selected={active} onClick={onClick} className={`focus-ring flex items-center gap-3 rounded-xl border p-3 text-left transition ${active ? "border-violet-500/40 bg-violet-500/10 text-white" : "border-white/10 bg-white/[0.02] text-zinc-500 hover:border-white/20 hover:text-zinc-300"}`}><span className={`grid h-8 w-8 place-items-center rounded-lg ${active ? "bg-violet-500/20 text-violet-300" : "bg-white/[0.04]"}`}>{icon}</span><span><span className="block text-[9px] font-black tracking-[0.16em]">{number}</span><span className="text-sm font-bold">{label}</span></span></button>;
}

function DerivedArtifactReview({ title, description, artifact, missingMessage, children }: { title: string; description: string; artifact?: Artifact; missingMessage?: string; children: ReactNode }) {
  return <section className="overflow-hidden rounded-xl border border-white/10 bg-[#141416]"><header className="flex flex-wrap items-start justify-between gap-4 border-b border-white/10 p-4"><div><p className="text-sm font-extrabold text-zinc-100">{title}</p><p className="mt-1 max-w-3xl text-xs leading-5 text-zinc-500">{description}</p></div>{artifact && <Button asChild type="button" variant="outline" size="sm"><a href={api.artifactUrl(artifact.download_url)}><Download size={14} />Download {artifact.name}</a></Button>}</header><div className="p-4">{artifact ? children : <EmptyReview text={missingMessage ?? `${title} will appear after the SDTM artifacts are generated.`} />}</div></section>;
}

function DefineArtifactPreview({ xml, html, diagnostics }: { xml?: Artifact; html?: Artifact; diagnostics?: Artifact }) {
  const [view, setView] = useState<"styled" | "raw" | "diagnostics">("styled");
  const query = useQuery({
    queryKey: ["artifact-text", view === "diagnostics" ? diagnostics?.id : xml?.id],
    queryFn: () => api.artifactText((view === "diagnostics" ? diagnostics : xml)!.download_url),
    enabled: view !== "styled" && Boolean(view === "diagnostics" ? diagnostics : xml),
  });
  if (!xml) return null;
  return <div><div className="mb-3 flex gap-2" role="tablist" aria-label="Define-XML views">{(["styled", "raw", "diagnostics"] as const).map((item) => <button key={item} type="button" role="tab" aria-selected={view === item} onClick={() => setView(item)} className={`rounded-lg px-3 py-2 text-xs font-bold capitalize ${view === item ? "bg-violet-500/15 text-violet-200" : "bg-white/[0.03] text-zinc-500"}`}>{item}</button>)}</div>{view === "styled" ? (html ? <iframe title="Styled Define-XML review" src={api.artifactPreviewUrl(html.download_url)} className="h-[48rem] w-full rounded-lg border border-white/10 bg-white" /> : <EmptyReview text="Styled Define-XML is unavailable." />) : query.isPending ? <EmptyReview text={`Loading Define-XML ${view} view…`} /> : query.isError ? <div className="rounded-lg border border-rose-500/20 bg-rose-500/10 p-4 text-sm text-rose-300">{query.error.message}</div> : <pre className="max-h-[48rem] overflow-auto rounded-lg border border-white/10 bg-[#09090b] p-4 font-mono text-xs leading-5 text-cyan-100"><code>{query.data}</code></pre>}</div>;
}

function ACRFArtifactReview({ pdf, diagnostics }: { pdf?: Artifact; diagnostics?: Artifact }) {
  const query = useQuery({ queryKey: ["acrf-diagnostics", diagnostics?.id], queryFn: () => api.artifactText(diagnostics!.download_url), enabled: Boolean(diagnostics) });
  let parsed: { status?: string; message?: string; annotations?: Array<{ domain: string; variable: string; status: string; page: number | null; label: string }> } = {};
  try { parsed = query.data ? JSON.parse(query.data) : {}; } catch { /* render unavailable diagnostics below */ }
  if (!pdf && parsed.status === "ocr_required") return <div className="rounded-xl border border-amber-500/20 bg-amber-500/[0.07] p-5 text-sm leading-6 text-amber-100">{parsed.message}</div>;
  if (!pdf) return <EmptyReview text="Annotated CRF output is unavailable." />;
  return <div className="grid gap-4 xl:grid-cols-[260px_minmax(0,1fr)]"><aside className="max-h-[48rem] overflow-auto rounded-lg border border-white/10 bg-black/20 p-3"><p className="text-xs font-black uppercase tracking-wider text-zinc-400">Annotation coverage</p><div className="mt-3 space-y-2">{parsed.annotations?.map((item, index) => <a key={`${item.domain}-${item.variable}-${index}`} href={item.page ? `${api.artifactPreviewUrl(pdf.download_url)}#page=${item.page}` : undefined} className="block rounded-lg border border-white/[0.08] p-2 text-xs"><span className={item.status === "matched" ? "text-emerald-300" : item.status === "ambiguous" ? "text-amber-300" : "text-rose-300"}>{item.status.toUpperCase()}</span><span className="ml-2 font-mono text-zinc-200">{item.domain}.{item.variable}</span><span className="mt-1 block text-zinc-600">{item.label || "No CRF label"}{item.page ? ` · page ${item.page}` : ""}</span></a>)}</div></aside><iframe title="Annotated CRF review" src={api.artifactPreviewUrl(pdf.download_url)} className="h-[48rem] w-full rounded-lg border border-white/10 bg-white" /></div>;
}

function SourceCard({ source }: { source: { name: string; type: SourceType } }) {
  return <div draggable onDragStart={(event) => { event.dataTransfer.effectAllowed = "copy"; event.dataTransfer.setData("application/x-sdtm-source", JSON.stringify(source)); }} className="flex cursor-grab items-center gap-3 rounded-lg border border-white/10 bg-white/[0.03] p-3 active:cursor-grabbing"><GripVertical size={16} className="text-zinc-600" /><div className="min-w-0 flex-1"><p className="truncate font-mono text-xs font-bold text-zinc-200">{source.name}</p><p className="mt-0.5 text-[10px] font-black uppercase tracking-wider text-violet-300">{source.type === "raw" ? "Raw dataset" : "Existing SDTM"}</p></div></div>;
}

function DomainDropZone({ dataset, mappings, onDrop, onUpdate, onRemove }: { dataset: SDTMDataset; mappings: DomainMapping[]; onDrop: (event: DragEvent) => void; onUpdate: (index: number, key: keyof DomainMapping, value: string) => void; onRemove: (index: number) => void }) {
  return <div onDragOver={(event) => { event.preventDefault(); event.dataTransfer.dropEffect = "copy"; }} onDrop={onDrop} className="rounded-xl border border-dashed border-violet-500/25 bg-violet-500/[0.035] p-4 transition hover:border-violet-400/50"><div className="flex items-start justify-between gap-3"><div><p className="font-mono text-base font-black text-violet-200">{dataset.domain}</p><p className="mt-1 text-xs text-zinc-400">{dataset.description}</p></div><span className="rounded-full border border-white/10 px-2 py-1 text-[9px] font-black uppercase tracking-wider text-zinc-500">Drop target</span></div><div className="mt-4 space-y-2">{mappings.map((mapping, index) => <div key={`${mapping.source_dataset}-${index}`} className="grid gap-2 rounded-lg border border-white/10 bg-[#111113] p-3 lg:grid-cols-[minmax(130px,0.8fr)_100px_110px_minmax(180px,1.4fr)_32px]"><div className="flex items-center gap-2"><span className="font-mono text-xs font-bold text-zinc-200">{mapping.source_dataset}</span><ArrowRight size={13} className="text-zinc-600" /><span className="font-mono text-xs font-bold text-violet-300">{dataset.domain}</span></div><select value={mapping.source_type} onChange={(event) => onUpdate(index, "source_type", event.target.value)} className={inputClass}><option value="raw">Raw</option><option value="sdtm">SDTM</option></select><select aria-label={`${mapping.source_dataset} to ${dataset.domain} relationship`} value={mapping.relationship} onChange={(event) => onUpdate(index, "relationship", event.target.value)} className={inputClass}><option value="direct">Direct</option><option value="stack">Stack</option><option value="join">Join</option><option value="split">Split</option><option value="derived">Derived</option></select><input value={mapping.rationale} onChange={(event) => onUpdate(index, "rationale", event.target.value)} placeholder="Mapping rationale" className={inputClass} /><button type="button" aria-label={`Remove ${mapping.source_dataset} mapping`} onClick={() => onRemove(index)} className="grid h-9 w-9 place-items-center rounded-md text-zinc-600 hover:bg-rose-500/10 hover:text-rose-300"><Trash2 size={14} /></button></div>)}{!mappings.length && <p className="rounded-lg border border-white/[0.07] bg-black/10 p-4 text-center text-xs text-zinc-600">Drop a raw or SDTM source dataset here.</p>}</div></div>;
}

function RelationshipGuide() {
  return <div className="grid gap-2 rounded-xl border border-white/10 bg-white/[0.02] p-3 text-[11px] leading-5 text-zinc-500 sm:grid-cols-2 xl:grid-cols-5"><span><strong className="text-emerald-300">Direct</strong> keeps one source&apos;s row structure.</span><span><strong className="text-violet-300">Stack</strong> appends observations as new rows.</span><span><strong className="text-sky-300">Join</strong> adds columns by reviewed keys and cardinality.</span><span><strong className="text-amber-300">Split</strong> routes one source to multiple domains.</span><span><strong className="text-zinc-300">Derived</strong> constructs records without a row-aligned source.</span></div>;
}

function DomainTabs({ datasets, selected, onSelect }: { datasets: SDTMDataset[]; selected: string; onSelect: (domain: string) => void }) {
  return <div className="flex flex-wrap gap-2">{datasets.map((dataset) => <button type="button" key={dataset.domain} onClick={() => onSelect(dataset.domain)} className={`focus-ring rounded-lg border px-3 py-2 font-mono text-xs font-bold ${selected === dataset.domain ? "border-violet-500/40 bg-violet-500/10 text-violet-200" : "border-white/10 bg-white/[0.02] text-zinc-500"}`}>{dataset.domain}</button>)}</div>;
}

type ProgramLanguage = "r" | "sas";
type SyntaxTokenKind = "plain" | "comment" | "string" | "keyword" | "number" | "function" | "operator" | "macro";
type SyntaxToken = { kind: SyntaxTokenKind; text: string };

const R_KEYWORDS = new Set(["break", "else", "FALSE", "for", "function", "if", "in", "Inf", "NA", "NaN", "next", "NULL", "repeat", "TRUE", "while"]);
const SAS_KEYWORDS = new Set(["and", "array", "as", "by", "case", "create", "data", "delete", "do", "drop", "else", "end", "first", "format", "from", "full", "group", "having", "if", "in", "infile", "inner", "input", "join", "keep", "last", "left", "length", "merge", "missing", "not", "on", "or", "order", "otherwise", "output", "proc", "quit", "rename", "retain", "right", "run", "select", "set", "table", "then", "when", "where"]);

function DomainProgramReview({ domain, artifacts }: { domain: string; artifacts: Artifact[] }) {
  const slug = domain.trim().replace(/[^A-Za-z0-9]+/g, "-").replace(/^-+|-+$/g, "").toLowerCase();
  const rArtifact = artifacts.find((artifact) => artifact.name.toLowerCase() === `build-${slug}.r`);
  const sasArtifact = artifacts.find((artifact) => artifact.name.toLowerCase() === `build-${slug}.sas`);
  const [language, setLanguage] = useState<ProgramLanguage>(rArtifact ? "r" : "sas");
  useEffect(() => setLanguage(rArtifact ? "r" : "sas"), [domain, rArtifact?.id, sasArtifact?.id]);
  const rQuery = useQuery({ queryKey: ["sdtm-program", rArtifact?.id, rArtifact?.sha256], queryFn: () => api.artifactText(rArtifact!.download_url), enabled: Boolean(rArtifact) });
  const sasQuery = useQuery({ queryKey: ["sdtm-program", sasArtifact?.id, sasArtifact?.sha256], queryFn: () => api.artifactText(sasArtifact!.download_url), enabled: Boolean(sasArtifact) });
  const artifact = language === "r" ? rArtifact : sasArtifact;
  const query = language === "r" ? rQuery : sasQuery;

  if (!rArtifact && !sasArtifact) {
    return <EmptyReview text={`Generated R/SAS program artifacts are unavailable for ${domain}. Save or rerun the reviewed mapping to build them.`} />;
  }
  return <article className="overflow-hidden rounded-xl border border-white/10 bg-[#111113]">
    <header className="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 p-4">
      <div><p className="font-mono text-sm font-black text-violet-200">{artifact?.name}</p><p className="mt-1 text-[11px] text-zinc-600">Exact generated artifact · read only{artifact ? ` · SHA-256 ${artifact.sha256.slice(0, 12)}…` : ""}</p></div>
      <div className="flex flex-wrap items-center gap-2">
        <div role="tablist" aria-label={`${domain} program languages`} className="flex rounded-lg border border-white/10 bg-black/20 p-1">
          {(["r", "sas"] as const).map((item) => {
            const available = item === "r" ? Boolean(rArtifact) : Boolean(sasArtifact);
            return <button key={item} type="button" role="tab" aria-selected={language === item} disabled={!available} onClick={() => setLanguage(item)} className={`rounded-md px-3 py-1.5 text-[10px] font-black uppercase tracking-wider ${language === item ? "bg-violet-500/20 text-violet-200" : available ? "text-zinc-500 hover:text-zinc-300" : "cursor-not-allowed text-zinc-800"}`}>{item === "r" ? "R" : "SAS"}</button>;
          })}
        </div>
        {artifact && <Button asChild type="button" variant="outline" size="sm"><a href={api.artifactUrl(artifact.download_url)}><Download size={14} />Download</a></Button>}
      </div>
    </header>
    <div className="p-4">
      {query.isPending ? <EmptyReview text={`Loading ${domain} ${language.toUpperCase()} program…`} /> : query.isError ? <div className="rounded-lg border border-rose-500/20 bg-rose-500/10 p-4 text-sm text-rose-300">{query.error.message}</div> : <SyntaxHighlightedProgram code={query.data ?? ""} language={language} label={`${domain} ${language.toUpperCase()} program`} />}
    </div>
  </article>;
}

function SyntaxHighlightedProgram({ code, language, label }: { code: string; language: ProgramLanguage; label: string }) {
  let inBlockComment = false;
  const lines = code.replace(/\r\n?/g, "\n").split("\n").map((line) => {
    const result = tokenizeProgramLine(line, language, inBlockComment);
    inBlockComment = result.inBlockComment;
    return result.tokens;
  });
  return <pre className="max-h-[48rem] overflow-auto rounded-lg border border-white/10 bg-[#08090c] py-3 font-mono text-xs leading-5 text-zinc-300"><code aria-label={label}>{lines.map((tokens, lineIndex) => <span className="block min-w-max px-3" key={lineIndex}><span aria-hidden="true" className="mr-4 inline-block w-9 select-none border-r border-white/[0.07] pr-3 text-right text-zinc-700">{lineIndex + 1}</span>{tokens.length ? tokens.map((token, tokenIndex) => <span data-token={token.kind} className={tokenClass(token.kind)} key={`${lineIndex}-${tokenIndex}`}>{token.text}</span>) : "\u00a0"}</span>)}</code></pre>;
}

function tokenizeProgramLine(line: string, language: ProgramLanguage, startsInBlockComment: boolean): { tokens: SyntaxToken[]; inBlockComment: boolean } {
  const tokens: SyntaxToken[] = [];
  let index = 0;
  let inBlockComment = startsInBlockComment;
  const push = (kind: SyntaxTokenKind, text: string) => { if (text) tokens.push({ kind, text }); };
  if (language === "sas" && !inBlockComment && /^\s*\*[^/].*;\s*$/.test(line)) return { tokens: [{ kind: "comment", text: line }], inBlockComment: false };
  while (index < line.length) {
    if (inBlockComment) {
      const end = line.indexOf("*/", index);
      if (end < 0) { push("comment", line.slice(index)); return { tokens, inBlockComment: true }; }
      push("comment", line.slice(index, end + 2));
      index = end + 2;
      inBlockComment = false;
      continue;
    }
    if (language === "r" && line[index] === "#") { push("comment", line.slice(index)); break; }
    if (language === "sas" && line.startsWith("/*", index)) {
      const end = line.indexOf("*/", index + 2);
      if (end < 0) { push("comment", line.slice(index)); inBlockComment = true; break; }
      push("comment", line.slice(index, end + 2));
      index = end + 2;
      continue;
    }
    const character = line[index];
    if (character === "\"" || character === "'") {
      let end = index + 1;
      while (end < line.length) {
        if (line[end] === character) {
          if (language === "sas" && line[end + 1] === character) { end += 2; continue; }
          end += 1;
          break;
        }
        if (line[end] === "\\" && language === "r") end += 1;
        end += 1;
      }
      push("string", line.slice(index, end));
      index = end;
      continue;
    }
    const remainder = line.slice(index);
    const whitespace = remainder.match(/^\s+/)?.[0];
    if (whitespace) { push("plain", whitespace); index += whitespace.length; continue; }
    const macro = language === "sas" ? remainder.match(/^[%&][A-Za-z_][A-Za-z0-9_]*/) : null;
    if (macro) { push("macro", macro[0]); index += macro[0].length; continue; }
    const number = remainder.match(/^(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?/i)?.[0];
    if (number) { push("number", number); index += number.length; continue; }
    const identifier = remainder.match(/^[A-Za-z_.][A-Za-z0-9_.$]*/)?.[0];
    if (identifier) {
      const keyword = language === "r" ? R_KEYWORDS.has(identifier) : SAS_KEYWORDS.has(identifier.toLowerCase());
      const isFunction = language === "r" && /^\s*\(/.test(line.slice(index + identifier.length));
      push(keyword ? "keyword" : isFunction ? "function" : "plain", identifier);
      index += identifier.length;
      continue;
    }
    const operator = remainder.match(/^(?:%[^%\s]+%|<-|->|:::{0,1}|==|!=|<=|>=|&&|\|\||\+|-|\*|\/|\^|=|<|>|!|&|\||~|:|\$)/)?.[0];
    if (operator) { push("operator", operator); index += operator.length; continue; }
    push("plain", character);
    index += 1;
  }
  return { tokens, inBlockComment };
}

function tokenClass(kind: SyntaxTokenKind): string {
  return { plain: "text-zinc-300", comment: "italic text-zinc-600", string: "text-amber-300", keyword: "font-semibold text-fuchsia-300", number: "text-sky-300", function: "text-cyan-300", operator: "text-violet-300", macro: "font-semibold text-emerald-300" }[kind];
}

function EditorLabel({ children }: { children: ReactNode }) { return <span className="mb-1.5 block text-[10px] font-black uppercase tracking-[0.12em] text-zinc-500">{children}</span>; }
function EmptyReview({ text }: { text: string }) { return <div className="grid min-h-64 place-items-center rounded-xl border border-dashed border-white/15 text-sm text-zinc-500">{text}</div>; }

function normalizePlan(value: Record<string, unknown>): SDTMPlanDraft {
  return {
    ...value,
    study_name: stringValue(value.study_name, "Untitled study"),
    standard: stringValue(value.standard, "SDTMIG 3.4"),
    define_standard: stringValue(value.define_standard, "Define-XML 2.1"),
    domain_mappings: arrayValue<DomainMapping>(value.domain_mappings),
    datasets: arrayValue<SDTMDataset>(value.datasets).map((dataset) => ({ ...dataset, record_plan: normalizeRecordPlan(dataset.record_plan), variables: arrayValue<SDTMVariable>(dataset.variables).map(normalizeVariable) })),
    rule_augmentations: arrayValue<VariableRule>(value.rule_augmentations),
    assumptions: arrayValue<string>(value.assumptions),
    unresolved_mappings: arrayValue<string>(value.unresolved_mappings),
  };
}

function reconcilePlan(plan: SDTMPlanDraft): SDTMPlanDraft {
  const domains = new Set(plan.datasets.map((dataset) => dataset.domain));
  plan.domain_mappings = plan.domain_mappings.filter((mapping) => domains.has(mapping.target_domain));
  const variableRules: VariableRule[] = [];
  plan.datasets.forEach((dataset) => {
    dataset.variables.forEach((variable) => {
      const existing = plan.rule_augmentations.find((rule) => rule.target_domain === dataset.domain && rule.target_variable === variable.name);
      variableRules.push(existing ?? newVariableRule(dataset.domain, variable));
    });
  });
  plan.rule_augmentations = variableRules;
  return plan;
}

function reviewIssues(plan: SDTMPlanDraft): string[] {
  const issues: string[] = [];
  if (!plan.datasets.length) issues.push("Import at least one target SDTM domain.");
  plan.datasets.forEach((dataset) => {
    const mappings = plan.domain_mappings.filter((mapping) => mapping.target_domain === dataset.domain);
    if (!mappings.length) issues.push(`${dataset.domain} needs at least one source dataset mapping.`);
    if (!dataset.variables.length) issues.push(`${dataset.domain} needs at least one variable.`);
    const available = new Set<string>();
    const reads = new Set<string>();
    dataset.record_plan.steps.forEach((step) => {
      if (!step.step_id.trim() || available.has(step.step_id)) issues.push(`${dataset.domain} record steps need unique IDs.`);
      [...step.inputs, ...(step.left ? [step.left] : []), ...(step.right ? [step.right] : [])].forEach((reference) => { if (!available.has(reference)) issues.push(`${dataset.domain}.${step.step_id} references unavailable step ${reference}.`); });
      if (step.operation === "read" && step.source_dataset) reads.add(step.source_dataset);
      if (step.operation === "stack" && step.inputs.length < 2) issues.push(`${dataset.domain}.${step.step_id} stack needs at least two inputs.`);
      if (step.operation === "join" && (!step.left || !step.right || !step.join_keys.length)) issues.push(`${dataset.domain}.${step.step_id} join needs both inputs and keys.`);
      available.add(step.step_id);
    });
    const operations = new Set(dataset.record_plan.steps.map((step) => step.operation));
    mappings.forEach((mapping) => {
      const requiredOperation = mapping.relationship === "stack" || mapping.relationship === "join" ? mapping.relationship : null;
      if (requiredOperation && !operations.has(requiredOperation)) issues.push(`${dataset.domain} ${requiredOperation} relationship needs a ${requiredOperation} record-plan operation.`);
    });
    mappings.forEach((mapping) => { if (!reads.has(mapping.source_dataset)) issues.push(`${dataset.domain} record plan must read ${mapping.source_dataset}.`); });
    if (!available.has(dataset.record_plan.output_step)) issues.push(`${dataset.domain} needs a valid final record step.`);
    dataset.variables.forEach((variable) => {
      if (!variable.name.trim()) issues.push(`${dataset.domain} has a variable without a target name.`);
      variable.sources.forEach((source) => { if (!source.dataset.trim() || !source.variable.trim()) issues.push(`${dataset.domain}.${variable.name || "[unnamed]"} has an incomplete source reference.`); else if (!mappings.some((mapping) => mapping.source_dataset === source.dataset)) issues.push(`${dataset.domain}.${variable.name || "[unnamed]"} uses an unmapped source dataset.`); });
      if (variable.mapping_type === "direct" && variable.sources.length !== 1) issues.push(`${dataset.domain}.${variable.name || "[unnamed]"} direct mapping needs exactly one source.`);
      if (variable.mapping_type === "assigned" && variable.sources.length) issues.push(`${dataset.domain}.${variable.name || "[unnamed]"} assigned mapping cannot have sources.`);
      if (!variable.sources.length && !allowsSourcelessOrigin(variable.origin)) issues.push(`${dataset.domain}.${variable.name || "[unnamed]"} needs an assigned or derived origin without a raw source.`);
      if (!variable.sources.length && (!variable.mapping_expression.trim() || variable.mapping_expression.trim().toLowerCase() === "direct")) issues.push(`${dataset.domain}.${variable.name || "[unnamed]"} needs explicit assignment or derivation logic.`);
    });
    issues.push(...vlmMatrixIssues(dataset.domain, dataset.variables));
  });
  return issues;
}

function datasetFromLibrary(response: CDISCDataset, plan: SDTMPlanDraft): SDTMDataset {
  const root = unwrapPayload(response.payload);
  const records = findVariableRecords(root);
  const source = plan.domain_mappings.find((mapping) => mapping.target_domain === response.domain)?.source_dataset ?? "";
  return {
    domain: response.domain,
    description: findString(root, ["label", "description", "definition", "name"]) || `${response.domain} imported from ${response.standard.toUpperCase()} ${response.version}`,
    structure: findString(root, ["structure", "datasetStructure"]) || "TODO: review CDISC dataset structure",
    key_variables: stringList(findValue(root, ["keyVariables", "keys"])) || ["STUDYID", "USUBJID"],
    record_plan: source ? { steps: [{ step_id: `read_${source.toLowerCase()}`, operation: "read", description: `Read ${source}`, output: `${response.domain.toLowerCase()}_source`, inputs: [], source_dataset: source, column_alignment: [], left: null, right: null, join_type: null, join_keys: [], cardinality: null, id_variables: [], value_variables: [], name_variable: null, value_variable: null, transpose_values: [], condition: null, sas_condition: null, keys: [], order_by: [], keep: "first", group_by: [], aggregations: [], review_notes: [] }], output_step: `read_${source.toLowerCase()}` } : { steps: [], output_step: "" },
    variables: records.map((record): SDTMVariable => {
      const name = findString(record, ["name", "variableName", "submissionValue", "code"]).toUpperCase();
      const variable = newSourceVariable(name, source);
      variable.label = findString(record, ["label", "description", "definition"]) || name;
      variable.data_type = numericType(findString(record, ["dataType", "datatype", "type"])) ? "Num" : "Char";
      variable.origin = "CDISC Library reference";
      return variable;
    }).filter((variable) => Boolean(variable.name)),
  };
}

function newVariableRule(domain: string, variable: SDTMVariable): VariableRule { return { rule_id: `${domain}-${variable.name || "NEW"}`, target_domain: domain, target_variable: variable.name, description: `Map ${domain}.${variable.name}`, logic: variable.mapping_expression || "TODO: review mapping logic", r_expression: "NA", sas_expression: ".", review_notes: ["User review required"] }; }

function unwrapPayload(value: unknown): unknown { if (isRecord(value) && Object.keys(value).length === 1 && "result" in value) return unwrapPayload(value.result); return value; }
function findVariableRecords(value: unknown): Record<string, unknown>[] { if (!isRecord(value) && !Array.isArray(value)) return []; if (isRecord(value)) { for (const key of ["variables", "datasetVariables", "dataset_variables", "items"]) { const candidate = value[key]; if (Array.isArray(candidate) && candidate.some((item) => isRecord(item) && Boolean(findString(item, ["name", "variableName", "submissionValue"])))) return candidate.filter(isRecord); } for (const candidate of Object.values(value)) { const found = findVariableRecords(candidate); if (found.length) return found; } } if (Array.isArray(value)) { for (const candidate of value) { const found = findVariableRecords(candidate); if (found.length) return found; } } return []; }
function findString(value: unknown, keys: string[]): string { const found = findValue(value, keys); return typeof found === "string" ? found : ""; }
function findValue(value: unknown, keys: string[]): unknown { if (!isRecord(value)) return undefined; for (const key of keys) if (value[key] !== undefined) return value[key]; return undefined; }
function numericType(value: string): boolean { return /num|integer|float|decimal/i.test(value); }
function stringList(value: unknown): string[] | null { if (!Array.isArray(value)) return null; const result = value.map((item) => typeof item === "string" ? item : isRecord(item) ? findString(item, ["name", "variable", "value"]) : "").filter(Boolean); return result.length ? result : null; }
function isRecord(value: unknown): value is Record<string, unknown> { return Boolean(value) && typeof value === "object" && !Array.isArray(value); }
function stringValue(value: unknown, fallback: string): string { return typeof value === "string" ? value : fallback; }
function arrayValue<T>(value: unknown): T[] { return Array.isArray(value) ? value as T[] : []; }
function allowsSourcelessOrigin(value: string): boolean { const normalized = value.trim().toLowerCase(); return ["assigned", "derived", "protocol", "system", "sponsor"].some((token) => normalized.includes(token)); }
function splitLines(value: string): string[] { return value.split("\n").map((item) => item.trim()).filter(Boolean); }
