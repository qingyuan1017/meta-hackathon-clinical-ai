"use client";

import { useEffect, useMemo, useState, type DragEvent, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight, BookOpen, Code2, Database, Download, FileCode2, FileScan, GripVertical, ListChecks, Play, Plus, Save, ScrollText, Table2, Trash2, Upload } from "lucide-react";
import { api } from "@/lib/api";
import type { Artifact, CDISCDataset, SDTMWorkbenchState, ValidationFinding } from "@/lib/types";
import { Button } from "./ui/button";

type SourceType = "raw" | "sdtm";
type DataType = "Char" | "Num";

interface DomainMapping {
  source_dataset: string;
  source_type: SourceType;
  target_domain: string;
  relationship: "direct" | "split" | "merge" | "derived";
  rationale: string;
}

interface ValueLevelMetadata {
  where_clause: string;
  label: string;
  data_type: DataType;
  origin: string;
  mapping_expression: string;
  controlled_terms: string[];
}

interface SDTMVariable {
  name: string;
  label: string;
  data_type: DataType;
  source_dataset: string;
  source_field: string;
  origin: string;
  mapping_expression: string;
  controlled_terms: string[];
  value_level_metadata: ValueLevelMetadata[];
  crf_source_label: string | null;
}

interface SDTMDataset {
  domain: string;
  description: string;
  structure: string;
  key_variables: string[];
  variables: SDTMVariable[];
}

interface DomainRule {
  rule_id: string;
  target_domain: string;
  source_datasets: string[];
  description: string;
  logic: string;
  r_input_expression: string;
  sas_input_statement: string;
  review_notes: string[];
}

interface VariableRule {
  rule_id: string;
  target_domain: string;
  target_variable: string;
  source_dependencies: string[];
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
  domain_rule_augmentations: DomainRule[];
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

  const sourceInventory = useMemo(() => {
    const sources = new Map<string, SourceType>();
    plan.domain_mappings.forEach((mapping) => sources.set(mapping.source_dataset, mapping.source_type));
    plan.datasets.flatMap((dataset) => dataset.variables).forEach((variable) => {
      if (variable.source_dataset) sources.set(variable.source_dataset, sources.get(variable.source_dataset) ?? "raw");
    });
    customSources.forEach((source) => sources.set(source.name, source.type));
    return Array.from(sources, ([name, type]) => ({ name, type }));
  }, [customSources, plan.datasets, plan.domain_mappings]);

  const activeDataset = plan.datasets.find((dataset) => dataset.domain === selectedDomain) ?? plan.datasets[0];
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
    dataset.variables.push(newVariable(`NEW${dataset.variables.length + 1}`, source));
  });

  const addSuppQualifier = (domain: string) => update((next) => {
    const dataset = next.datasets.find((item) => item.domain === domain);
    if (!dataset) return;
    const source = next.domain_mappings.find((mapping) => mapping.target_domain === domain)?.source_dataset ?? "";
    let qval = dataset.variables.find((variable) => variable.name === "QVAL");
    if (!qval) {
      qval = newVariable("QVAL", source);
      qval.label = "Data Value";
      dataset.variables.push(qval);
    }
    qval.value_level_metadata.push({
      where_clause: "QNAM = 'SPONSOR_VAR'",
      label: "Sponsor supplemental qualifier",
      data_type: "Char",
      origin: "Assigned",
      mapping_expression: "TODO: define sponsor qualifier mapping",
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
        <StageButton active={stage === "rules"} icon={<Code2 size={16} />} number="03" label="Rule augmentation" onClick={() => setStage("rules")} />
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
                <div><p className="text-sm font-bold text-zinc-100">{activeDataset.domain} · {activeDataset.description}</p><p className="mt-1 text-xs text-zinc-500">Each row is an SDTM variable. Value-level metadata is edited in the VLM column.</p></div>
                <div className="flex flex-wrap gap-2"><Button type="button" variant="outline" size="sm" onClick={() => addVariable(activeDataset.domain)}><Plus size={14} />Variable</Button><Button type="button" variant="outline" size="sm" onClick={() => addSuppQualifier(activeDataset.domain)}><Plus size={14} />SUPP/VLM qualifier</Button></div>
              </div>
              <div className="overflow-x-auto">
                <table className="min-w-[1500px] w-full border-collapse text-left text-xs">
                  <thead className="bg-white/[0.03] text-[10px] uppercase tracking-wider text-zinc-500"><tr>{["SDTM variable", "Label / type", "Source dataset", "Source field", "Mapping", "Origin / CT", "aCRF label", "VLM", ""].map((heading) => <th key={heading} className="border-b border-r border-white/10 px-3 py-2.5 font-black last:border-r-0">{heading}</th>)}</tr></thead>
                  <tbody>{activeDataset.variables.map((variable, variableIndex) => (
                    <VariableRow key={`${variable.name}-${variableIndex}`} variable={variable} onUpdate={(key, nextValue) => update((next) => {
                      const target = next.datasets.find((dataset) => dataset.domain === activeDataset.domain)?.variables[variableIndex];
                      if (!target) return;
                      const previousName = target.name;
                      const previousDependency = target.source_dataset && target.source_field ? `${target.source_dataset}.${target.source_field}` : "";
                      (target as unknown as Record<string, unknown>)[key] = nextValue;
                      const rule = next.rule_augmentations.find((item) => item.target_domain === activeDataset.domain && item.target_variable === previousName);
                      if (!rule) return;
                      if (key === "name") {
                        rule.target_variable = String(nextValue);
                        rule.rule_id = `${activeDataset.domain}-${String(nextValue)}`;
                      }
                      if (key === "source_dataset" || key === "source_field") {
                        const dependency = target.source_dataset && target.source_field ? `${target.source_dataset}.${target.source_field}` : "";
                        if (rule.source_dependencies.length <= 1 || rule.source_dependencies[0] === previousDependency) rule.source_dependencies = dependency ? [dependency] : [];
                      }
                    })} onUpdateVlm={(vlmIndex, key, nextValue) => update((next) => {
                      const target = next.datasets.find((dataset) => dataset.domain === activeDataset.domain)?.variables[variableIndex]?.value_level_metadata[vlmIndex];
                      if (target) (target as unknown as Record<string, unknown>)[key] = nextValue;
                    })} onAddVlm={() => update((next) => {
                      next.datasets.find((dataset) => dataset.domain === activeDataset.domain)?.variables[variableIndex]?.value_level_metadata.push({ where_clause: "", label: "", data_type: "Char", origin: "CRF", mapping_expression: "", controlled_terms: [] });
                    })} onRemoveVlm={(vlmIndex) => update((next) => {
                      const target = next.datasets.find((dataset) => dataset.domain === activeDataset.domain)?.variables[variableIndex];
                      if (target) target.value_level_metadata.splice(vlmIndex, 1);
                    })} onRemove={() => update((next) => {
                      next.datasets.find((dataset) => dataset.domain === activeDataset.domain)?.variables.splice(variableIndex, 1);
                    })} />
                  ))}</tbody>
                </table>
              </div>
            </section>
          ) : <EmptyReview text="Import or add an SDTM domain before reviewing variables." />}
        </div>
      )}

      {stage === "rules" && (
        <div className="space-y-5">
          <section className="space-y-3">
            <div><p className="text-xs font-black uppercase tracking-[0.12em] text-zinc-400">Domain source preparation</p><p className="mt-1 text-xs text-zinc-600">Review the input/join logic that feeds each target-domain transformation.</p></div>
            {plan.domain_rule_augmentations.map((rule, index) => <DomainRuleEditor key={rule.rule_id} rule={rule} onUpdate={(key, nextValue) => update((next) => { (next.domain_rule_augmentations[index] as unknown as Record<string, unknown>)[key] = nextValue; })} />)}
          </section>
          <section className="space-y-3">
            <div><p className="text-xs font-black uppercase tracking-[0.12em] text-zinc-400">Variable rule review</p><p className="mt-1 text-xs text-zinc-600">Expressions are draft code inputs. After approval, R may run only in the isolated runner when raw data is present; SAS remains export-only.</p></div>
            {plan.rule_augmentations.map((rule, index) => <VariableRuleEditor key={`${rule.target_domain}-${rule.target_variable}`} rule={rule} onUpdate={(key, nextValue) => update((next) => { (next.rule_augmentations[index] as unknown as Record<string, unknown>)[key] = nextValue; })} />)}
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
        <div>{issues.length ? <p className="flex items-center gap-2 text-xs font-bold text-amber-200"><AlertTriangle size={15} />{issues[0]}{issues.length > 1 ? ` (+${issues.length - 1} more)` : ""}</p> : <p className="text-xs font-bold text-emerald-300">All mapping references are ready for schema validation.</p>}{error && <p className="mt-1 text-xs text-rose-300">{error}</p>}</div>
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
  return <div onDragOver={(event) => { event.preventDefault(); event.dataTransfer.dropEffect = "copy"; }} onDrop={onDrop} className="rounded-xl border border-dashed border-violet-500/25 bg-violet-500/[0.035] p-4 transition hover:border-violet-400/50"><div className="flex items-start justify-between gap-3"><div><p className="font-mono text-base font-black text-violet-200">{dataset.domain}</p><p className="mt-1 text-xs text-zinc-400">{dataset.description}</p></div><span className="rounded-full border border-white/10 px-2 py-1 text-[9px] font-black uppercase tracking-wider text-zinc-500">Drop target</span></div><div className="mt-4 space-y-2">{mappings.map((mapping, index) => <div key={`${mapping.source_dataset}-${index}`} className="grid gap-2 rounded-lg border border-white/10 bg-[#111113] p-3 lg:grid-cols-[minmax(130px,0.8fr)_100px_110px_minmax(180px,1.4fr)_32px]"><div className="flex items-center gap-2"><span className="font-mono text-xs font-bold text-zinc-200">{mapping.source_dataset}</span><ArrowRight size={13} className="text-zinc-600" /><span className="font-mono text-xs font-bold text-violet-300">{dataset.domain}</span></div><select value={mapping.source_type} onChange={(event) => onUpdate(index, "source_type", event.target.value)} className={inputClass}><option value="raw">Raw</option><option value="sdtm">SDTM</option></select><select value={mapping.relationship} onChange={(event) => onUpdate(index, "relationship", event.target.value)} className={inputClass}><option value="direct">Direct</option><option value="split">Split</option><option value="merge">Merge</option><option value="derived">Derived</option></select><input value={mapping.rationale} onChange={(event) => onUpdate(index, "rationale", event.target.value)} placeholder="Mapping rationale" className={inputClass} /><button type="button" aria-label={`Remove ${mapping.source_dataset} mapping`} onClick={() => onRemove(index)} className="grid h-9 w-9 place-items-center rounded-md text-zinc-600 hover:bg-rose-500/10 hover:text-rose-300"><Trash2 size={14} /></button></div>)}{!mappings.length && <p className="rounded-lg border border-white/[0.07] bg-black/10 p-4 text-center text-xs text-zinc-600">Drop a raw or SDTM source dataset here.</p>}</div></div>;
}

function DomainTabs({ datasets, selected, onSelect }: { datasets: SDTMDataset[]; selected: string; onSelect: (domain: string) => void }) {
  return <div className="flex flex-wrap gap-2">{datasets.map((dataset) => <button type="button" key={dataset.domain} onClick={() => onSelect(dataset.domain)} className={`focus-ring rounded-lg border px-3 py-2 font-mono text-xs font-bold ${selected === dataset.domain ? "border-violet-500/40 bg-violet-500/10 text-violet-200" : "border-white/10 bg-white/[0.02] text-zinc-500"}`}>{dataset.domain}</button>)}</div>;
}

function VariableRow({ variable, onUpdate, onUpdateVlm, onAddVlm, onRemoveVlm, onRemove }: { variable: SDTMVariable; onUpdate: (key: keyof SDTMVariable, value: unknown) => void; onUpdateVlm: (index: number, key: keyof ValueLevelMetadata, value: unknown) => void; onAddVlm: () => void; onRemoveVlm: (index: number) => void; onRemove: () => void }) {
  return <tr className="align-top hover:bg-white/[0.015]"><td className="border-b border-r border-white/[0.07] p-2"><input value={variable.name} onChange={(event) => onUpdate("name", event.target.value.toUpperCase())} className={`${inputClass} font-mono font-bold text-violet-200`} /></td><td className="min-w-48 border-b border-r border-white/[0.07] p-2"><input value={variable.label} onChange={(event) => onUpdate("label", event.target.value)} className={inputClass} /><select value={variable.data_type} onChange={(event) => onUpdate("data_type", event.target.value)} className={`${inputClass} mt-1`}><option value="Char">Char</option><option value="Num">Num</option></select></td><td className="border-b border-r border-white/[0.07] p-2"><input value={variable.source_dataset} onChange={(event) => onUpdate("source_dataset", event.target.value)} className={inputClass} /></td><td className="border-b border-r border-white/[0.07] p-2"><input value={variable.source_field} onChange={(event) => onUpdate("source_field", event.target.value)} className={inputClass} /></td><td className="min-w-56 border-b border-r border-white/[0.07] p-2"><textarea rows={3} value={variable.mapping_expression} onChange={(event) => onUpdate("mapping_expression", event.target.value)} className={inputClass} /></td><td className="min-w-44 border-b border-r border-white/[0.07] p-2"><input value={variable.origin} onChange={(event) => onUpdate("origin", event.target.value)} className={inputClass} /><input value={variable.controlled_terms.join(", ")} onChange={(event) => onUpdate("controlled_terms", splitList(event.target.value))} placeholder="Controlled terms" className={`${inputClass} mt-1`} /></td><td className="border-b border-r border-white/[0.07] p-2"><input value={variable.crf_source_label ?? ""} onChange={(event) => onUpdate("crf_source_label", event.target.value || null)} className={inputClass} /></td><td className="min-w-[360px] border-b border-r border-white/[0.07] p-2"><div className="space-y-2">{variable.value_level_metadata.map((vlm, index) => <div key={index} className="rounded-lg border border-cyan-500/15 bg-cyan-500/[0.04] p-2"><div className="grid grid-cols-2 gap-1"><input value={vlm.where_clause} onChange={(event) => onUpdateVlm(index, "where_clause", event.target.value)} placeholder="Where clause" className={inputClass} /><input value={vlm.label} onChange={(event) => onUpdateVlm(index, "label", event.target.value)} placeholder="VLM label" className={inputClass} /></div><textarea rows={2} value={vlm.mapping_expression} onChange={(event) => onUpdateVlm(index, "mapping_expression", event.target.value)} placeholder="Mapping value / expression" className={`${inputClass} mt-1`} /><div className="mt-1 flex gap-1"><input value={vlm.controlled_terms.join(", ")} onChange={(event) => onUpdateVlm(index, "controlled_terms", splitList(event.target.value))} placeholder="Controlled terms" className={inputClass} /><button type="button" aria-label="Remove VLM" onClick={() => onRemoveVlm(index)} className="grid h-9 w-9 shrink-0 place-items-center rounded-md text-zinc-600 hover:bg-rose-500/10 hover:text-rose-300"><Trash2 size={13} /></button></div></div>)}<button type="button" onClick={onAddVlm} className="flex w-full items-center justify-center gap-1 rounded-md border border-dashed border-white/10 py-2 text-[10px] font-black uppercase tracking-wider text-zinc-500 hover:border-cyan-500/30 hover:text-cyan-300"><Plus size={12} />VLM mapping</button></div></td><td className="border-b border-white/[0.07] p-2"><button type="button" aria-label={`Remove ${variable.name}`} onClick={onRemove} className="grid h-9 w-9 place-items-center rounded-md text-zinc-600 hover:bg-rose-500/10 hover:text-rose-300"><Trash2 size={14} /></button></td></tr>;
}

function DomainRuleEditor({ rule, onUpdate }: { rule: DomainRule; onUpdate: (key: keyof DomainRule, value: unknown) => void }) {
  return <article className="overflow-hidden rounded-xl border border-white/10 bg-[#141416]"><header className="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 px-4 py-3"><div><span className="font-mono text-xs font-black text-violet-300">{rule.target_domain}</span><span className="ml-2 text-xs text-zinc-500">{rule.rule_id}</span></div><span className="rounded-full bg-blue-500/10 px-2 py-1 text-[9px] font-black uppercase tracking-wider text-blue-300">Domain rule</span></header><div className="grid gap-4 p-4 lg:grid-cols-2"><label><EditorLabel>Logic review</EditorLabel><textarea value={rule.logic} onChange={(event) => onUpdate("logic", event.target.value)} className={codeClass} /></label><label><EditorLabel>Review notes</EditorLabel><textarea value={rule.review_notes.join("\n")} onChange={(event) => onUpdate("review_notes", splitLines(event.target.value))} placeholder="One review note per line" className={codeClass} /></label><label><EditorLabel>R input expression</EditorLabel><textarea value={rule.r_input_expression} onChange={(event) => onUpdate("r_input_expression", event.target.value)} className={codeClass} spellCheck={false} /></label><label><EditorLabel>SAS SET / MERGE statement</EditorLabel><textarea value={rule.sas_input_statement} onChange={(event) => onUpdate("sas_input_statement", event.target.value)} className={codeClass} spellCheck={false} /></label></div></article>;
}

function VariableRuleEditor({ rule, onUpdate }: { rule: VariableRule; onUpdate: (key: keyof VariableRule, value: unknown) => void }) {
  return <article className="overflow-hidden rounded-xl border border-white/10 bg-[#141416]"><header className="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 px-4 py-3"><div><span className="font-mono text-xs font-black text-violet-300">{rule.target_domain}.{rule.target_variable}</span><span className="ml-2 text-xs text-zinc-500">{rule.rule_id}</span></div><input value={rule.source_dependencies.join(", ")} onChange={(event) => onUpdate("source_dependencies", splitList(event.target.value))} aria-label={`${rule.target_domain}.${rule.target_variable} source dependencies`} className={`${inputClass} max-w-md font-mono`} /></header><div className="grid gap-4 p-4 lg:grid-cols-2"><label className="lg:col-span-2"><EditorLabel>Language-neutral mapping logic</EditorLabel><textarea value={rule.logic} onChange={(event) => onUpdate("logic", event.target.value)} className={`${codeClass} min-h-20`} /></label><label><EditorLabel>R right-hand-side expression</EditorLabel><textarea value={rule.r_expression} onChange={(event) => onUpdate("r_expression", event.target.value)} className={codeClass} spellCheck={false} /></label><label><EditorLabel>SAS right-hand-side expression</EditorLabel><textarea value={rule.sas_expression} onChange={(event) => onUpdate("sas_expression", event.target.value)} className={codeClass} spellCheck={false} /></label><label className="lg:col-span-2"><EditorLabel>Review notes</EditorLabel><textarea value={rule.review_notes.join("\n")} onChange={(event) => onUpdate("review_notes", splitLines(event.target.value))} className={`${codeClass} min-h-20`} /></label></div></article>;
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
    datasets: arrayValue<SDTMDataset>(value.datasets).map((dataset) => ({ ...dataset, variables: arrayValue<SDTMVariable>(dataset.variables).map((variable) => ({ ...variable, source_dataset: stringValue(variable.source_dataset, ""), source_field: stringValue(variable.source_field, ""), controlled_terms: arrayValue<string>(variable.controlled_terms), value_level_metadata: arrayValue<ValueLevelMetadata>(variable.value_level_metadata) })) })),
    domain_rule_augmentations: arrayValue<DomainRule>(value.domain_rule_augmentations),
    rule_augmentations: arrayValue<VariableRule>(value.rule_augmentations),
    assumptions: arrayValue<string>(value.assumptions),
    unresolved_mappings: arrayValue<string>(value.unresolved_mappings),
  };
}

function reconcilePlan(plan: SDTMPlanDraft): SDTMPlanDraft {
  const domains = new Set(plan.datasets.map((dataset) => dataset.domain));
  plan.domain_mappings = plan.domain_mappings.filter((mapping) => domains.has(mapping.target_domain));
  plan.domain_rule_augmentations = plan.datasets.map((dataset) => {
    const existing = plan.domain_rule_augmentations.find((rule) => rule.target_domain === dataset.domain) ?? newDomainRule(dataset.domain);
    existing.source_datasets = Array.from(new Set(plan.domain_mappings.filter((mapping) => mapping.target_domain === dataset.domain).map((mapping) => mapping.source_dataset)));
    return existing;
  });
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
    dataset.variables.forEach((variable) => {
      if (!variable.name.trim()) issues.push(`${dataset.domain} has a variable without a target name.`);
      const hasDataset = Boolean(variable.source_dataset.trim());
      const hasField = Boolean(variable.source_field.trim());
      if (hasDataset !== hasField) issues.push(`${dataset.domain}.${variable.name || "[unnamed]"} needs both a source dataset and field, or neither.`);
      if (hasDataset && !mappings.some((mapping) => mapping.source_dataset === variable.source_dataset)) issues.push(`${dataset.domain}.${variable.name || "[unnamed]"} uses an unmapped source dataset.`);
      if (!hasDataset && !allowsSourcelessOrigin(variable.origin)) issues.push(`${dataset.domain}.${variable.name || "[unnamed]"} needs an assigned or derived origin without a raw source.`);
      if (!hasDataset && (!variable.mapping_expression.trim() || variable.mapping_expression.trim().toLowerCase() === "direct")) issues.push(`${dataset.domain}.${variable.name || "[unnamed]"} needs explicit assignment or derivation logic.`);
    });
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
    variables: records.map((record): SDTMVariable => {
      const name = findString(record, ["name", "variableName", "submissionValue", "code"]).toUpperCase();
      const variable = newVariable(name, source);
      variable.label = findString(record, ["label", "description", "definition"]) || name;
      variable.data_type = numericType(findString(record, ["dataType", "datatype", "type"])) ? "Num" : "Char";
      variable.origin = "CDISC Library reference";
      return variable;
    }).filter((variable) => Boolean(variable.name)),
  };
}

function newVariable(name: string, source: string): SDTMVariable { return { name, label: name, data_type: "Char", source_dataset: source, source_field: name, origin: "Assigned", mapping_expression: "TODO: review mapping", controlled_terms: [], value_level_metadata: [], crf_source_label: null }; }
function newDomainRule(domain: string): DomainRule { return { rule_id: `${domain}-SOURCE`, target_domain: domain, source_datasets: [], description: `Prepare ${domain} source records`, logic: "TODO: review source preparation", r_input_expression: "TODO_SOURCE", sas_input_statement: "/* TODO: SET or MERGE source datasets; */", review_notes: ["User review required"] }; }
function newVariableRule(domain: string, variable: SDTMVariable): VariableRule { return { rule_id: `${domain}-${variable.name || "NEW"}`, target_domain: domain, target_variable: variable.name, source_dependencies: variable.source_dataset && variable.source_field ? [`${variable.source_dataset}.${variable.source_field}`] : [], description: `Map ${domain}.${variable.name}`, logic: variable.mapping_expression || "TODO: review mapping logic", r_expression: "NA", sas_expression: ".", review_notes: ["User review required"] }; }

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
function splitList(value: string): string[] { return value.split(",").map((item) => item.trim()).filter(Boolean); }
function splitLines(value: string): string[] { return value.split("\n").map((item) => item.trim()).filter(Boolean); }
