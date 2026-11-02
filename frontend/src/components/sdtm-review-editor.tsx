"use client";

import { useEffect, useMemo, useRef, useState, type DragEvent, type MutableRefObject, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight, BookOpen, Code2, Database, Download, FileCode2, FileScan, GripVertical, ListChecks, Play, Plus, Save, ScrollText, Table2, Trash2, Upload } from "lucide-react";
import { api } from "@/lib/api";
import type { Artifact, CDISCDataset, ExecutionAttempt, Job, SDTMWorkbenchState, ValidationFinding } from "@/lib/types";
import type { RevisionFeedbackEvent } from "@/lib/revision-decision";
import { useOptionalReviewDraft } from "@/lib/review-draft-context";
import { Button } from "./ui/button";
import { groupOperationsByDomain, ReviewPatchPanel } from "./review-patch-panel";
import { RevisionDecisionPanel } from "./revision-decision-panel";
import {
  VariableMappingMatrix,
  newSourceVariable,
  normalizeRecordPlan,
  normalizeVariable,
  vlmMatrixIssues,
  type SDTMACRFAnnotationDraft,
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
  acrf_font_family?: "Helvetica" | "Helvetica Bold" | "Times" | "Times Bold" | "Courier" | "Courier Bold";
  acrf_font_size?: number;
  acrf_text_color?: string;
  acrf_fill_color?: string;
  acrf_domain_annotation?: ACRFDomainAnnotation;
  review_assumptions: string[];
  review_unresolved_mappings: string[];
  variables: SDTMVariable[];
}

interface ACRFPosition { page: number; x: number; y: number; }
interface ACRFDomainAnnotation { enabled: boolean; text: string; positions: ACRFPosition[]; }
interface ACRFFreeAnnotation extends ACRFPosition {
  id: string;
  text: string;
  font_family: "Helvetica" | "Helvetica Bold" | "Times" | "Times Bold" | "Courier" | "Courier Bold";
  font_size: number;
  text_color: string;
  fill_color: string;
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
  acrf_free_annotations: ACRFFreeAnnotation[];
  assumptions: string[];
  unresolved_mappings: string[];
}

type Stage = "domains" | "variables" | "rules" | "execution" | "acrf" | "define" | "validation" | "csdrg";

const inputClass = "focus-ring min-h-9 w-full rounded-md border border-white/10 bg-[#101012] px-2.5 py-2 text-xs text-zinc-200 placeholder:text-zinc-600";
const codeClass = "focus-ring min-h-28 w-full resize-y rounded-lg border border-white/10 bg-[#0a0a0c] p-3 font-mono text-xs leading-5 text-zinc-200 placeholder:text-zinc-700";

export function SDTMReviewEditor({ jobId, workbench, value, artifacts = [], onChange, onSave, saving, error, reviewJob, feedbackEvents, initialStage = "domains" }: {
  jobId?: string;
  workbench?: SDTMWorkbenchState | null;
  value: Record<string, unknown>;
  artifacts?: Artifact[];
  onChange: (value: SDTMPlanDraft) => void;
  onSave: (value: SDTMPlanDraft) => void;
  saving: boolean;
  error?: string | null;
  reviewJob?: Job;
  feedbackEvents?: RevisionFeedbackEvent[];
  initialStage?: Stage;
}) {
  const plan = normalizePlan(value);
  const [stage, setStage] = useState<Stage>(initialStage);
  const [selectedDomain, setSelectedDomain] = useState(plan.datasets[0]?.domain ?? "");
  const [customSources, setCustomSources] = useState<Array<{ name: string; type: SourceType }>>([]);
  const [sourceName, setSourceName] = useState("");
  const [sourceType, setSourceType] = useState<SourceType>("raw");
  const [libraryDomain, setLibraryDomain] = useState("");
  const [libraryVersion, setLibraryVersion] = useState("3-4");
  const [libraryStandard, setLibraryStandard] = useState<"sdtm" | "sdtmig">("sdtmig");
  const [libraryBusy, setLibraryBusy] = useState(false);
  const [libraryError, setLibraryError] = useState<string | null>(null);
  const reviewDraft = useOptionalReviewDraft();
  const setSdtmRevisionContext = reviewDraft?.setSdtmRevisionContext;
  const proposalReview = Boolean(reviewJob?.review_patch);
  const feedbackCounts = useMemo(() => new Map(
    reviewJob?.review_patch
      ? groupOperationsByDomain(reviewJob.review_patch.operations, value).map((group) => [group.domain, group.operations.length])
      : [],
  ), [reviewJob?.review_patch, value]);

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
  const ownedAssumptions = new Set(plan.datasets.flatMap((dataset) => dataset.review_assumptions));
  const ownedUnresolved = new Set(plan.datasets.flatMap((dataset) => dataset.review_unresolved_mappings));
  const stageAssumptions = plan.assumptions.filter((item) => !ownedAssumptions.has(item));
  const stageUnresolved = plan.unresolved_mappings.filter((item) => !ownedUnresolved.has(item));
  const activeProposalOperations = activeDataset && reviewJob?.review_patch
    ? reviewJob.review_patch.operations.filter((operation) => operation.path.includes(`/datasets/domain=${encodePatchSelector(activeDataset.domain)}/`))
    : [];

  useEffect(() => setStage(initialStage), [initialStage, reviewJob?.review_patch?.transaction_id]);

  useEffect(() => {
    if (!setSdtmRevisionContext) return;
    if (!jobId) {
      setSdtmRevisionContext(null);
      return;
    }
    const domain = activeDataset?.domain;
    if (stage === "domains") setSdtmRevisionContext({ surface: "domain_mapping", label: "Domain Mapping" });
    else if (stage === "variables" && domain) setSdtmRevisionContext({ surface: "variable_mapping", label: `Variable & VLM · ${domain}`, domain });
    else if (stage === "rules" && domain) setSdtmRevisionContext({ surface: "rule_augmentation", label: `Rule & Code · ${domain}`, domain });
    else if (stage === "execution") return;
    else if (stage === "acrf" && domain) setSdtmRevisionContext({ surface: "acrf", label: `aCRF metadata · ${domain}`, domain });
    else if (stage === "define" && domain) setSdtmRevisionContext({ surface: "define_xml", label: `Define-XML metadata · ${domain}`, domain });
    else if (stage === "csdrg") setSdtmRevisionContext({ surface: "csdrg", label: "cSDRG narrative" });
    else setSdtmRevisionContext(null);
    return () => setSdtmRevisionContext(null);
  }, [activeDataset?.domain, jobId, setSdtmRevisionContext, stage]);

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
      <div className={`rounded-xl border p-4 ${proposalReview ? "border-amber-500/25 bg-amber-500/[0.08]" : "border-violet-500/20 bg-violet-500/[0.06]"}`}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div><p className={`text-xs font-black uppercase tracking-[0.14em] ${proposalReview ? "text-amber-200" : "text-violet-300"}`}>{proposalReview ? "Review gate · agent proposal" : "SDTM review workspace"}</p><p className={`mt-1 text-sm ${proposalReview ? "text-amber-100/80" : "text-zinc-300"}`}>{proposalReview ? "Review the proposed changes, recorded decisions, and assumptions in the same workspace used for stage review. Approved artifacts remain active until you accept this transaction." : "Review each mapping stage, then inspect the derived aCRF and Define-XML. Saving revalidates the complete plan and rebuilds every artifact."}</p></div>
          <span className="rounded-full border border-amber-500/25 bg-amber-500/10 px-3 py-1 text-[10px] font-black uppercase tracking-wider text-amber-200">{proposalReview ? "Proposal · review required" : "Draft · review required"}</span>
        </div>
        {workbench && <div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">{Object.entries(workbench.lifecycle).map(([label, status]) => <div key={label} className="rounded-lg border border-white/10 bg-black/15 px-3 py-2"><p className="text-[9px] font-black uppercase tracking-wider text-zinc-500">{label.replaceAll("_", " ")}</p><p className={`mt-1 text-xs font-bold ${status === "passed" || status === "completed" || status === "ready" ? "text-emerald-300" : status === "failed" || status === "blocked" || status === "unavailable" ? "text-rose-300" : "text-amber-200"}`}>{status.replaceAll("_", " ")}</p></div>)}</div>}
      </div>

      {proposalReview && <RevisionDecisionPanel result={{ assumptions: stageAssumptions, unresolved_mappings: stageUnresolved }} events={feedbackEvents} title="Stage-wide feedback decisions" assumptionsTitle="Stage-wide assumptions" ariaLabel="Stage-wide feedback decisions" onlyMatchedFeedback collapsedByDefault />}

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
                <div key={dataset.domain}><DomainDropZone dataset={dataset} mappings={plan.domain_mappings.filter((mapping) => mapping.target_domain === dataset.domain)} onDrop={(event) => onDrop(event, dataset.domain)} onUpdate={(mappingIndex, key, nextValue) => update((next) => {
                  const mapping = next.domain_mappings.filter((item) => item.target_domain === dataset.domain)[mappingIndex];
                  if (mapping) (mapping as unknown as Record<string, unknown>)[key] = nextValue;
                })} onRemove={(mappingIndex) => update((next) => {
                  const matching = next.domain_mappings.filter((item) => item.target_domain === dataset.domain);
                  const target = matching[mappingIndex];
                  next.domain_mappings = next.domain_mappings.filter((item) => item !== target);
                })} />{reviewJob?.review_patch && <ReviewPatchPanel job={reviewJob} domain={dataset.domain} />}</div>
              ))}
              {!plan.datasets.length && <p className="rounded-xl border border-dashed border-white/15 p-10 text-center text-sm text-zinc-500">Import a target SDTM domain from CDISC Library to begin mapping.</p>}
              {reviewJob?.review_patch && <ReviewPatchPanel job={reviewJob} domain="General" />}
            </section>
          </div>
        </div>
      )}

      {stage === "variables" && (
        <div className="space-y-4">
          <DomainTabs datasets={plan.datasets} selected={activeDataset?.domain ?? ""} onSelect={setSelectedDomain} feedbackCounts={feedbackCounts} />
          {activeDataset ? (
            <section className="overflow-hidden rounded-xl border border-white/10 bg-[#141416]">
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 p-4">
                <div><p className="text-sm font-bold text-zinc-100">{activeDataset.domain} · {activeDataset.description}</p><p className="mt-1 text-xs text-zinc-500">Use the variable-by-source matrix to edit target metadata, minor derivations, detailed lineage, and VLM rows.</p></div>
                <div className="flex flex-wrap gap-2"><Button type="button" variant="outline" size="sm" onClick={() => addVariable(activeDataset.domain)}><Plus size={14} />Variable</Button><Button type="button" variant="outline" size="sm" onClick={() => addSuppQualifier(activeDataset.domain)}><Plus size={14} />SUPP/VLM qualifier</Button></div>
              </div>
              {(activeDataset.review_assumptions.length > 0 || activeDataset.review_unresolved_mappings.length > 0) && <div className="border-b border-white/10 p-4"><RevisionDecisionPanel result={{ assumptions: activeDataset.review_assumptions, unresolved_mappings: activeDataset.review_unresolved_mappings }} events={feedbackEvents} title={`${activeDataset.domain} feedback decisions`} assumptionsTitle={`${activeDataset.domain} assumptions`} ariaLabel={`${activeDataset.domain} feedback decisions`} onlyMatchedFeedback collapsedByDefault /></div>}
              <div className="space-y-4 p-4">
                <VariableMappingMatrix variables={activeDataset.variables} inventory={sourceInventory} allowedDatasets={plan.domain_mappings.filter((mapping) => mapping.target_domain === activeDataset.domain).map((mapping) => mapping.source_dataset)} sourceRelationships={plan.domain_mappings.filter((mapping) => mapping.target_domain === activeDataset.domain).map((mapping) => ({ dataset: mapping.source_dataset, relationship: mapping.relationship }))} domain={activeDataset.domain} proposalOperations={activeProposalOperations} onSelectedVariableChange={(variable) => setSdtmRevisionContext?.({ surface: "variable_mapping", label: variable ? `Variable & VLM · ${activeDataset.domain}.${variable}` : `Variable & VLM · ${activeDataset.domain}`, domain: activeDataset.domain, variable: variable ?? undefined })} onChange={(variables) => update((next) => {
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
                {reviewJob?.review_patch && <ReviewPatchPanel job={reviewJob} domain={activeDataset.domain} />}
              </div>
            </section>
          ) : <EmptyReview text="Import or add an SDTM domain before reviewing variables." />}
        </div>
      )}

      {stage === "rules" && (
        <div className="space-y-5">
          <DomainTabs datasets={plan.datasets} selected={activeRuleDomain} onSelect={setSelectedDomain} feedbackCounts={feedbackCounts} />
          <section className="space-y-3">
            <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-xs font-black uppercase tracking-[0.12em] text-zinc-400">{activeRuleDomain || "Domain"} program review</p><p className="mt-1 text-xs text-zinc-600">Review or manually edit the exact R and SAS artifacts. Saving resets prior execution and validation evidence; use the right-side agent when you want a review-gated mapping or rule revision.</p></div></div>
            {activeDataset && (activeDataset.review_assumptions.length > 0 || activeDataset.review_unresolved_mappings.length > 0) && <RevisionDecisionPanel result={{ assumptions: activeDataset.review_assumptions, unresolved_mappings: activeDataset.review_unresolved_mappings }} events={feedbackEvents} title={`${activeDataset.domain} feedback decisions`} assumptionsTitle={`${activeDataset.domain} assumptions`} ariaLabel={`${activeDataset.domain} feedback decisions`} onlyMatchedFeedback collapsedByDefault />}
            {activeRuleDomain ? <DomainProgramReview jobId={jobId} domain={activeRuleDomain} artifacts={artifacts} editable={!proposalReview} /> : <EmptyReview text="No SDTM domain is available for program review." />}
            {reviewJob?.review_patch && activeRuleDomain && <ReviewPatchPanel job={reviewJob} domain={activeRuleDomain} />}
          </section>
        </div>
      )}

      {stage === "execution" && <ExecutionReview jobId={jobId} workbench={workbench} datasets={plan.datasets} domain={activeRuleDomain} onDomainChange={setSelectedDomain} />}

      {stage === "acrf" && (
        <DerivedArtifactReview
          title="Annotated CRF review"
          description="Review by domain, drag annotations to exact page locations, manage the domain label shown on each applicable page, and add page annotations such as NOT SUBMITTED that are not tied to an SDTM domain."
          artifact={acrfArtifact ?? acrfDiagnostics}
          missingMessage="No aCRF was generated because this job did not include a blank CRF PDF. Start a new generation with a blank CRF to enable annotation review."
        >
          <ACRFArtifactReview
            jobId={jobId}
            pdf={acrfArtifact}
            diagnostics={acrfDiagnostics}
            plan={plan}
            onAnnotationsChange={(domain, variableName, annotations) => update((next) => {
              const variable = next.datasets.find((dataset) => dataset.domain === domain)?.variables.find((item) => item.name === variableName);
              if (variable) { variable.acrf_annotations = annotations; variable.crf_source_label = null; }
            })}
            onDomainStyleChange={(domain, patch) => update((next) => {
              const dataset = next.datasets.find((item) => item.domain === domain);
              if (dataset) Object.assign(dataset, patch);
            })}
            onDomainAnnotationChange={(domain, annotation) => update((next) => {
              const dataset = next.datasets.find((item) => item.domain === domain);
              if (dataset) dataset.acrf_domain_annotation = annotation;
            })}
            onFreeAnnotationsChange={(annotations) => update((next) => { next.acrf_free_annotations = annotations; })}
            onSave={() => onSave(plan)}
            saving={saving}
            saveDisabled={issues.length > 0}
            error={error}
          />
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

      {!proposalReview && <div className="sticky bottom-3 z-20 flex flex-col gap-3 rounded-xl border border-white/15 bg-[#161619]/95 p-4 shadow-2xl backdrop-blur sm:flex-row sm:items-center sm:justify-between">
        <div>{issues.length ? <p className="flex items-center gap-2 text-xs font-bold text-amber-200"><AlertTriangle size={15} />{issues[0]}{issues.length > 1 ? ` (+${issues.length - 1} more)` : ""}</p> : <p className="text-xs font-bold text-emerald-300">All mapping references are ready for schema validation.</p>}{error && <p className="mt-1 text-xs text-rose-300">{error}</p>}</div>
        <Button type="button" variant="clinical" onClick={() => onSave(plan)} disabled={saving || issues.length > 0}><Save size={16} />{saving ? "Validating and rebuilding…" : "Save reviewed mappings"}</Button>
      </div>}
    </div>
  );
}

function executionAttemptDomains(attempt: ExecutionAttempt): string[] {
  return Array.from(new Set([
    ...attempt.checks.filter((check) => check.status === "failed" && check.domain).map((check) => check.domain!),
    ...(attempt.repair_proposal?.change.domain ? [attempt.repair_proposal.change.domain] : []),
  ])).sort();
}

function isExecutionRepairCandidate(attempt: ExecutionAttempt): boolean {
  return attempt.status === "failed" || attempt.status === "timed_out" || attempt.status === "review_required";
}

function ExecutionReview({ jobId, workbench, datasets, domain, onDomainChange }: {
  jobId?: string;
  workbench?: SDTMWorkbenchState | null;
  datasets: SDTMDataset[];
  domain: string;
  onDomainChange: (domain: string) => void;
}) {
  const client = useQueryClient();
  const revisionContext = useOptionalReviewDraft();
  const [rawFiles, setRawFiles] = useState<File[]>([]);
  const [selectedAttemptId, setSelectedAttemptId] = useState<string | null>(null);
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
  const rawDatasets = workbench?.inputs.raw_datasets ?? [];
  const attempts = query.data?.items ?? [];
  const selectedAttempt = attempts.find((attempt) => attempt.attempt_id === selectedAttemptId && isExecutionRepairCandidate(attempt));

  useEffect(() => {
    const candidates = attempts.filter(isExecutionRepairCandidate);
    if (!candidates.length) {
      setSelectedAttemptId(null);
      return;
    }
    if (!selectedAttemptId || !candidates.some((attempt) => attempt.attempt_id === selectedAttemptId)) {
      const latest = candidates[candidates.length - 1];
      setSelectedAttemptId(latest.attempt_id);
      const implicated = executionAttemptDomains(latest);
      if (implicated.length && !implicated.includes(domain)) onDomainChange(implicated[0]);
    }
  }, [attempts, domain, onDomainChange, selectedAttemptId]);

  useEffect(() => {
    if (!jobId || !domain || !revisionContext?.setSdtmRevisionContext) return;
    const implicated = selectedAttempt ? executionAttemptDomains(selectedAttempt) : [];
    const evidenceMatches = Boolean(selectedAttempt) && (!implicated.length || implicated.includes(domain));
    const attemptLabel = evidenceMatches ? ` · ${selectedAttempt!.attempt_id}` : "";
    revisionContext.setSdtmRevisionContext({
      surface: "execution",
      label: `Rule & Code repair · ${domain}${attemptLabel}`,
      domain,
      executionAttemptId: evidenceMatches ? selectedAttempt?.attempt_id : undefined,
    });
  }, [domain, jobId, revisionContext?.setSdtmRevisionContext, selectedAttempt]);

  const selectAttempt = (attempt: ExecutionAttempt) => {
    setSelectedAttemptId(attempt.attempt_id);
    const implicated = executionAttemptDomains(attempt);
    if (implicated.length && !implicated.includes(domain)) onDomainChange(implicated[0]);
  };

  return <div className="space-y-4">
    <section className="space-y-3 rounded-xl border border-violet-500/20 bg-violet-500/[0.05] p-4">
      <div><p className="text-xs font-black uppercase tracking-[0.12em] text-violet-300">Rule & Code repair target</p><p className="mt-1 text-xs leading-5 text-zinc-400">Select the failed attempt and affected domain here. Add guidance, voice input, and scope in the right-side agent; its proposed rule/code changes still require full stage review and approval.</p></div>
      <DomainTabs datasets={datasets} selected={domain} onSelect={onDomainChange} />
      {selectedAttempt && <p className="rounded-lg border border-violet-500/20 bg-black/20 px-3 py-2 text-xs text-violet-100">Selected evidence: <span className="font-mono font-bold">{selectedAttempt.attempt_id}</span> · sanitized logs, failed checks, and failure classification will be attached to the {domain} Rule & Code agent.</p>}
      {!selectedAttempt && <p className="text-xs text-zinc-500">Run the reviewed R program first. A failed or timed-out attempt can then be selected as repair evidence.</p>}
    </section>
    <section className="rounded-xl border border-white/10 bg-[#141416] p-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div><p className="text-sm font-extrabold text-zinc-100">Isolated R execution</p><p className="mt-1 max-w-3xl text-xs leading-5 text-zinc-500">Each domain R program runs independently in the dedicated network-isolated runner, so one domain failure does not prevent other domains from completing. SAS remains export-only. Output checks confirm readability and expected structure; they are not standards validation.</p></div>
        <span className="rounded-full border border-white/10 px-3 py-1 text-[10px] font-black uppercase tracking-wider text-zinc-300">{workbench?.lifecycle.execution?.replaceAll("_", " ") ?? "not run"}</span>
      </div>
      <div className="mt-4 grid gap-3 md:grid-cols-2">
        {rawDatasets.map((dataset) => <div key={dataset.logical_name} className="rounded-lg border border-white/10 bg-white/[0.025] p-3"><p className="font-mono text-xs font-bold text-violet-200">{dataset.logical_name}.{dataset.format}</p><p className="mt-1 text-[11px] text-zinc-500">{dataset.row_count ?? "Unknown"} rows · {dataset.columns.length} columns · SHA-256 {dataset.sha256.slice(0, 12)}…</p></div>)}
        {!rawDatasets.length && <p className="text-xs text-amber-200">No raw datasets were supplied. Programs are generated but cannot be executed.</p>}
      </div>
      <label className="mt-4 block rounded-lg border border-dashed border-white/15 p-3 text-xs text-zinc-400"><span className="flex items-center gap-2 font-bold text-zinc-300"><Upload size={14} />Add raw data after mapping approval</span><input className="mt-2 block w-full" type="file" accept=".csv,.xpt" multiple onChange={(event) => setRawFiles(Array.from(event.target.files ?? []))} /></label>
      <Button type="button" variant="clinical" className="mt-3" disabled={!jobId || mutation.isPending || (!rawDatasets.length && !rawFiles.length)} onClick={() => mutation.mutate()}><Play size={15} />{mutation.isPending ? "Running in isolation…" : "Execute reviewed R"}</Button>
      {mutation.error && <p className="mt-3 text-xs text-rose-300">{mutation.error.message}</p>}
    </section>
    <section className="space-y-3">
      <p className="text-xs font-black uppercase tracking-wider text-zinc-400">Immutable attempt history</p>
      {attempts.map((attempt) => {
        const candidate = isExecutionRepairCandidate(attempt);
        const selected = selectedAttemptId === attempt.attempt_id;
        const implicated = executionAttemptDomains(attempt);
        return <article key={attempt.attempt_id} className={`rounded-xl border p-4 ${selected ? "border-violet-400/40 bg-violet-500/[0.08]" : "border-white/10 bg-[#141416]"}`}>
        <div className="flex flex-wrap justify-between gap-2"><div><p className="font-mono text-xs font-bold text-violet-200">{attempt.attempt_id}</p><p className="mt-1 text-[11px] text-zinc-500">Program SHA-256 {attempt.program_hash} · exit {attempt.exit_code ?? "not available"}</p></div><span className={`rounded-full px-2 py-1 text-[10px] font-black uppercase ${attempt.status === "passed" ? "bg-emerald-500/10 text-emerald-300" : "bg-rose-500/10 text-rose-300"}`}>{attempt.status.replaceAll("_", " ")}</span></div>
        <label className={`mt-3 flex items-start gap-2 rounded-lg border px-3 py-2 text-xs ${candidate ? "cursor-pointer border-violet-500/20 text-zinc-200" : "border-white/[0.06] text-zinc-600"}`}><input type="radio" name="execution-repair-evidence" className="mt-0.5 accent-violet-500" checked={selected} disabled={!candidate} onChange={() => selectAttempt(attempt)} /><span><span className="font-bold">{candidate ? "Use as Rule & Code evidence" : "Not eligible as repair evidence"}</span>{implicated.length > 0 && <span className="mt-0.5 block text-[11px] text-zinc-500">Implicated {implicated.join(", ")}</span>}</span></label>
        {attempt.checks.some((check) => check.check_id === "domain-execution") && <div className="mt-3"><p className="text-[10px] font-black uppercase tracking-wider text-zinc-500">Independent domain execution</p><div className="mt-2 flex flex-wrap gap-2">{attempt.checks.filter((check) => check.check_id === "domain-execution").map((check) => <span key={`${attempt.attempt_id}-${check.domain}`} className={`rounded-full border px-2.5 py-1 text-[10px] font-black uppercase ${check.status === "passed" ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-300" : check.status === "not_run" ? "border-zinc-500/20 bg-zinc-500/10 text-zinc-400" : "border-rose-500/20 bg-rose-500/10 text-rose-300"}`}>{check.domain} · {check.status.replaceAll("_", " ")}</span>)}</div></div>}
        {attempt.failure_classification && <p className="mt-3 text-xs text-amber-200">Failure classification: {attempt.failure_classification.replaceAll("_", " ")}</p>}
        {attempt.repair_proposal && <div className="mt-3 rounded-lg border border-amber-500/20 bg-amber-500/[0.06] p-3"><p className="text-xs font-bold text-amber-100">Typed repair proposal · {attempt.repair_proposal.status}</p><p className="mt-1 text-xs text-zinc-300">{attempt.repair_proposal.rationale}</p><pre className="mt-2 overflow-auto rounded bg-black/30 p-2 text-[11px] text-cyan-100">{attempt.repair_proposal.diff}</pre>{attempt.repair_proposal.status === "proposed" && <div className="mt-3 flex gap-2"><Button type="button" variant="clinical" size="sm" disabled={repairMutation.isPending} onClick={() => repairMutation.mutate({ attemptId: attempt.attempt_id, proposalId: attempt.repair_proposal!.proposal_id, approved: true })}>Approve and rerun</Button><Button type="button" variant="outline" size="sm" disabled={repairMutation.isPending} onClick={() => repairMutation.mutate({ attemptId: attempt.attempt_id, proposalId: attempt.repair_proposal!.proposal_id, approved: false })}>Reject</Button></div>}</div>}
        <div className="mt-3 grid gap-2 md:grid-cols-2">{attempt.checks.filter((check) => check.check_id !== "domain-execution").map((check, index) => <div key={`${check.check_id}-${index}`} className="rounded-lg border border-white/[0.08] p-2 text-xs"><span className={check.status === "passed" ? "text-emerald-300" : check.status === "warning" || check.status === "not_run" ? "text-amber-300" : "text-rose-300"}>{check.status.toUpperCase()}</span><span className="ml-2 text-zinc-400">{check.message}</span></div>)}</div>
        {(attempt.stdout || attempt.stderr) && <details className="mt-3"><summary className="cursor-pointer text-xs font-bold text-zinc-400">Sanitized runner logs</summary><pre className="mt-2 max-h-64 overflow-auto rounded-lg bg-black/30 p-3 text-[11px] text-zinc-400">{[attempt.stdout, attempt.stderr].filter(Boolean).join("\n")}</pre></details>}
      </article>})}
      {!query.isPending && !attempts.length && <EmptyReview text="No R execution attempts have been recorded." />}
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
  const reviewDraft = useOptionalReviewDraft();
  const query = useQuery({ queryKey: ["csdrg-source", source?.id], queryFn: () => api.artifactText(source!.download_url), enabled: Boolean(source) });
  const [draft, setDraft] = useState("");
  useEffect(() => {
    if (reviewDraft?.csdrgAgentDraft) setDraft(JSON.stringify(reviewDraft.csdrgAgentDraft, null, 2));
    else if (query.data) setDraft(query.data);
  }, [query.data, reviewDraft?.csdrgAgentDraft]);
  const mutation = useMutation({ mutationFn: () => { const parsed: unknown = JSON.parse(draft); if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") throw new Error("cSDRG source must be a JSON object."); return api.updateCsdrg(jobId!, parsed as Record<string, unknown>); }, onSuccess: () => { reviewDraft?.setCsdrgAgentDraft(null); client.invalidateQueries({ queryKey: ["job", jobId] }); client.invalidateQueries({ queryKey: ["csdrg-source"] }); } });
  if (!source) return <EmptyReview text="cSDRG artifacts will appear after the SDTM plan is generated." />;
  return <div className="space-y-4"><section className="rounded-xl border border-white/10 bg-[#141416] p-4"><div className="flex flex-wrap justify-between gap-3"><div><p className="text-sm font-extrabold text-zinc-100">Editable cSDRG source</p><p className="mt-1 text-xs leading-5 text-zinc-500">Narrative sections may be edited. Use the right-side agent for narrative revisions. Execution, validation, unresolved issues, limitations, and reviewer-approved explanations remain evidence-controlled by the backend.</p></div>{pdf && <Button asChild type="button" variant="outline" size="sm"><a href={api.artifactUrl(pdf.download_url)}><Download size={14} />Download csdrg.pdf</a></Button>}</div><textarea aria-label="Editable cSDRG JSON" value={draft} onChange={(event) => setDraft(event.target.value)} className={`${codeClass} mt-4 min-h-[32rem]`} spellCheck={false} /><Button type="button" variant="clinical" className="mt-3" disabled={!jobId || mutation.isPending} onClick={() => mutation.mutate()}><Save size={15} />Save cSDRG review</Button>{mutation.error && <p className="mt-2 text-xs text-rose-300">{mutation.error.message}</p>}</section>{pdf && <iframe title="cSDRG PDF review" src={api.artifactPreviewUrl(pdf.download_url)} className="h-[48rem] w-full rounded-xl border border-white/10 bg-white" />}</div>;
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

const ACRF_FONT_FAMILIES = ["Helvetica", "Helvetica Bold", "Times", "Times Bold", "Courier", "Courier Bold"] as const;
const DEFAULT_ACRF_STYLE = { font_family: "Helvetica", font_size: 8, text_color: "#141F3D", fill_color: "#EBF2FF" } as const;
type ACRFDomainStylePatch = Partial<Pick<SDTMDataset, "acrf_font_family" | "acrf_font_size" | "acrf_text_color" | "acrf_fill_color">>;
type ACRFDiagnosticAnnotation = { annotation_type?: "variable" | "domain" | "free"; annotation_id?: string; domain: string; variable: string; annotation_index: number; status: string; page: number | null; label: string; mapping_text: string; textbox?: [number, number, number, number] | null };
type ACRFPage = { page: number; width: number; height: number };

function acrfAnnotationKey(domain: string, variable: string, index: number) { return `${domain}.${variable}.${index}`; }
function acrfEditorKey(annotation: ACRFDiagnosticAnnotation) {
  if (annotation.annotation_type === "domain") return `domain:${annotation.domain}`;
  if (annotation.annotation_type === "free") return `free:${annotation.annotation_id}`;
  return acrfAnnotationKey(annotation.domain, annotation.variable, annotation.annotation_index);
}
function newFreeAnnotationId() { return `free-${Date.now()}-${Math.random().toString(16).slice(2)}`; }

function ACRFArtifactReview({ jobId, pdf, diagnostics, plan, onAnnotationsChange, onDomainStyleChange, onDomainAnnotationChange, onFreeAnnotationsChange, onSave, saving, saveDisabled, error }: {
  jobId?: string;
  pdf?: Artifact;
  diagnostics?: Artifact;
  plan: SDTMPlanDraft;
  onAnnotationsChange: (domain: string, variable: string, annotations: SDTMACRFAnnotationDraft[]) => void;
  onDomainStyleChange: (domain: string, patch: ACRFDomainStylePatch) => void;
  onDomainAnnotationChange: (domain: string, annotation: ACRFDomainAnnotation) => void;
  onFreeAnnotationsChange: (annotations: ACRFFreeAnnotation[]) => void;
  onSave: () => void;
  saving: boolean;
  saveDisabled: boolean;
  error?: string | null;
}) {
  const query = useQuery({ queryKey: ["acrf-diagnostics", diagnostics?.id], queryFn: () => api.artifactText(diagnostics!.download_url), enabled: Boolean(diagnostics) });
  const revisionContext = useOptionalReviewDraft();
  const [selectedDomain, setSelectedDomain] = useState(plan.datasets[0]?.domain ?? "");
  const [selectedAnnotation, setSelectedAnnotation] = useState<string | null>(null);
  const editorRefs = useRef(new Map<string, HTMLElement>());
  const pageRefs = useRef(new Map<number, HTMLDivElement>());
  let parsed: { status?: string; message?: string; annotations?: ACRFDiagnosticAnnotation[]; pages?: ACRFPage[]; domain_styles?: Record<string, typeof DEFAULT_ACRF_STYLE> } = {};
  try { parsed = query.data ? JSON.parse(query.data) : {}; } catch { /* render unavailable diagnostics below */ }
  useEffect(() => {
    if (!plan.datasets.some((dataset) => dataset.domain === selectedDomain)) setSelectedDomain(plan.datasets[0]?.domain ?? "");
  }, [plan.datasets, selectedDomain]);
  useEffect(() => {
    if (!jobId || !selectedDomain || !revisionContext?.setSdtmRevisionContext) return;
    revisionContext.setSdtmRevisionContext({ surface: "acrf", label: `aCRF metadata · ${selectedDomain}`, domain: selectedDomain });
  }, [jobId, revisionContext?.setSdtmRevisionContext, selectedDomain]);
  useEffect(() => {
    if (!selectedAnnotation) return;
    const editor = editorRefs.current.get(selectedAnnotation);
    editor?.scrollIntoView?.({ block: "nearest", behavior: "smooth" });
    editor?.querySelector<HTMLInputElement>("input")?.focus();
  }, [selectedAnnotation, selectedDomain]);
  if (!pdf && parsed.status === "ocr_required") return <div className="rounded-xl border border-amber-500/20 bg-amber-500/[0.07] p-5 text-sm leading-6 text-amber-100">{parsed.message}</div>;
  if (!pdf) return <EmptyReview text="Annotated CRF output is unavailable." />;
  const dataset = plan.datasets.find((item) => item.domain === selectedDomain) ?? plan.datasets[0];
  if (!dataset) return <EmptyReview text="No SDTM domains are available for aCRF review." />;
  const domainAnnotation = dataset.acrf_domain_annotation ?? { enabled: true, text: dataset.domain, positions: [] };
  const freeAnnotations = plan.acrf_free_annotations ?? [];
  const savedAnnotations = new Map((parsed.annotations ?? []).map((item) => [acrfAnnotationKey(item.domain, item.variable, item.annotation_index), item]));
  const annotationCount = dataset.variables.reduce((count, variable) => count + (variable.acrf_annotations?.length ?? 0), 0);
  const style = {
    font_family: dataset.acrf_font_family ?? DEFAULT_ACRF_STYLE.font_family,
    font_size: dataset.acrf_font_size ?? DEFAULT_ACRF_STYLE.font_size,
    text_color: (dataset.acrf_text_color ?? DEFAULT_ACRF_STYLE.text_color).toUpperCase(),
    fill_color: (dataset.acrf_fill_color ?? DEFAULT_ACRF_STYLE.fill_color).toUpperCase(),
  };
  const savedStyle = parsed.domain_styles?.[dataset.domain] ?? DEFAULT_ACRF_STYLE;
  const stylePending = style.font_family !== savedStyle.font_family || style.font_size !== savedStyle.font_size || style.text_color !== savedStyle.text_color.toUpperCase() || style.fill_color !== savedStyle.fill_color.toUpperCase();
  const selectAnnotation = (annotation: ACRFDiagnosticAnnotation) => {
    if (annotation.domain) setSelectedDomain(annotation.domain);
    setSelectedAnnotation(acrfEditorKey(annotation));
    if (annotation.page) pageRefs.current.get(annotation.page)?.scrollIntoView?.({ block: "nearest", behavior: "smooth" });
  };
  const moveAnnotation = (annotation: ACRFDiagnosticAnnotation, position: ACRFPosition) => {
    if (annotation.annotation_type === "domain") {
      const targetDataset = plan.datasets.find((item) => item.domain === annotation.domain);
      const current = targetDataset?.acrf_domain_annotation ?? { enabled: true, text: annotation.domain, positions: [] };
      const positions = [...current.positions.filter((item) => item.page !== position.page), position];
      onDomainAnnotationChange(annotation.domain, { ...current, positions });
    } else if (annotation.annotation_type === "free") {
      onFreeAnnotationsChange(freeAnnotations.map((item) => item.id === annotation.annotation_id ? { ...item, ...position } : item));
    } else {
      const variable = plan.datasets.find((item) => item.domain === annotation.domain)?.variables.find((item) => item.name === annotation.variable);
      if (variable) onAnnotationsChange(annotation.domain, annotation.variable, (variable.acrf_annotations ?? []).map((item, index) => index === annotation.annotation_index ? { ...item, ...position } : item));
    }
  };
  return <div className="grid gap-4 xl:grid-cols-[430px_minmax(0,1fr)]">
    <aside className="flex max-h-[48rem] min-h-0 flex-col overflow-hidden rounded-lg border border-white/10 bg-black/20">
      <div className="border-b border-white/10 p-3">
        <div className="flex items-center justify-between gap-3"><div><p className="text-xs font-black uppercase tracking-wider text-zinc-400">aCRF mappings</p><p className="mt-1 text-[11px] leading-4 text-zinc-600">{annotationCount} annotation{annotationCount === 1 ? "" : "s"} in {dataset.domain}.</p></div><Button type="button" variant="clinical" size="sm" onClick={onSave} disabled={saving || saveDisabled}><Save size={14} />{saving ? "Rebuilding…" : "Save & rebuild"}</Button></div>
        <label className="mt-3 block"><span className="mb-1 block text-[9px] font-bold uppercase tracking-wider text-zinc-500">Domain</span><select aria-label="aCRF domain" value={dataset.domain} onChange={(event) => { setSelectedDomain(event.target.value); setSelectedAnnotation(null); }} className={inputClass}>{plan.datasets.map((item) => <option key={item.domain} value={item.domain}>{item.domain} - {item.description}</option>)}</select></label>
        <div className={`mt-3 rounded-lg border p-2.5 ${stylePending ? "border-sky-500/30 bg-sky-500/[0.06]" : "border-white/[0.08] bg-white/[0.02]"}`}>
          <div className="flex items-center justify-between"><span className="text-[9px] font-black uppercase tracking-wider text-zinc-500">{dataset.domain} annotation style</span>{stylePending && <span className="text-[9px] font-bold uppercase text-sky-300">Pending rebuild</span>}</div>
          <div className="mt-2 grid grid-cols-[minmax(0,1fr)_78px] gap-2"><select aria-label={`aCRF font for ${dataset.domain}`} value={style.font_family} onChange={(event) => onDomainStyleChange(dataset.domain, { acrf_font_family: event.target.value as SDTMDataset["acrf_font_family"] })} className={inputClass}>{ACRF_FONT_FAMILIES.map((font) => <option key={font}>{font}</option>)}</select><input aria-label={`aCRF font size for ${dataset.domain}`} type="number" min={6} max={18} step={0.5} value={style.font_size} onChange={(event) => onDomainStyleChange(dataset.domain, { acrf_font_size: Math.min(18, Math.max(6, Number(event.target.value) || 8)) })} className={inputClass} /></div>
          <div className="mt-2 grid grid-cols-2 gap-2"><label className="flex items-center gap-2 rounded-md border border-white/10 bg-[#101012] px-2 py-1.5"><input aria-label={`aCRF text color for ${dataset.domain}`} type="color" value={style.text_color} onChange={(event) => onDomainStyleChange(dataset.domain, { acrf_text_color: event.target.value.toUpperCase() })} className="h-6 w-8 cursor-pointer bg-transparent p-0" /><span className="text-[9px] font-bold uppercase text-zinc-500">Text</span></label><label className="flex items-center gap-2 rounded-md border border-white/10 bg-[#101012] px-2 py-1.5"><input aria-label={`aCRF background color for ${dataset.domain}`} type="color" value={style.fill_color} onChange={(event) => onDomainStyleChange(dataset.domain, { acrf_fill_color: event.target.value.toUpperCase() })} className="h-6 w-8 cursor-pointer bg-transparent p-0" /><span className="text-[9px] font-bold uppercase text-zinc-500">Background</span></label></div>
        </div>
        <p className="mt-2 text-[10px] leading-4 text-zinc-600">Drag any box in the page preview to persist a new location. Variable and domain boxes inherit this domain style.</p>
        {error && <p className="mt-2 rounded-md border border-rose-500/20 bg-rose-500/10 px-2 py-1.5 text-[10px] text-rose-300">{error}</p>}
      </div>
      <div className="min-h-0 flex-1 space-y-2 overflow-auto p-3">
        <article ref={(node) => { if (node) editorRefs.current.set(`domain:${dataset.domain}`, node); else editorRefs.current.delete(`domain:${dataset.domain}`); }} className={`rounded-lg border p-2.5 ${selectedAnnotation === `domain:${dataset.domain}` ? "border-violet-400 bg-violet-500/[0.08]" : "border-violet-500/20 bg-violet-500/[0.04]"}`}>
          <div className="flex items-center justify-between gap-2"><div><span className="text-[10px] font-black uppercase tracking-wider text-violet-300">Domain annotation</span><p className="mt-1 text-[10px] text-zinc-600">Shown at the top-left of every page containing a {dataset.domain} variable annotation.</p></div><input aria-label={`Enable ${dataset.domain} domain annotation`} type="checkbox" checked={domainAnnotation.enabled} onChange={(event) => onDomainAnnotationChange(dataset.domain, { ...domainAnnotation, enabled: event.target.checked })} /></div>
          <input aria-label={`Domain annotation text for ${dataset.domain}`} value={domainAnnotation.text} disabled={!domainAnnotation.enabled} onChange={(event) => onDomainAnnotationChange(dataset.domain, { ...domainAnnotation, text: event.target.value })} placeholder={dataset.domain} className={`${inputClass} mt-2`} />
          <p className="mt-2 text-[9px] text-zinc-600">{domainAnnotation.positions.length ? `${domainAnnotation.positions.length} page position${domainAnnotation.positions.length === 1 ? "" : "s"} customized.` : "Using automatic top-left placement."}</p>
        </article>
        <article className="rounded-lg border border-amber-500/20 bg-amber-500/[0.035] p-2.5">
          <div className="flex items-center justify-between gap-2"><div><span className="text-[10px] font-black uppercase tracking-wider text-amber-300">No-domain annotations</span><p className="mt-1 text-[10px] text-zinc-600">Page notes such as NOT SUBMITTED.</p></div><button type="button" onClick={() => { const annotation: ACRFFreeAnnotation = { id: newFreeAnnotationId(), text: "NOT SUBMITTED", page: 1, x: 48, y: 48, font_family: "Helvetica Bold", font_size: 9, text_color: "#7F1D1D", fill_color: "#FEE2E2" }; onFreeAnnotationsChange([...freeAnnotations, annotation]); setSelectedAnnotation(`free:${annotation.id}`); }} className="text-[10px] font-bold text-amber-300"><Plus size={11} className="mr-1 inline" />Add</button></div>
          {freeAnnotations.map((annotation, index) => <div key={annotation.id} ref={(node) => { if (node) editorRefs.current.set(`free:${annotation.id}`, node); else editorRefs.current.delete(`free:${annotation.id}`); }} className={`mt-2 rounded-md border p-2 ${selectedAnnotation === `free:${annotation.id}` ? "border-amber-300 bg-amber-500/[0.08]" : "border-white/[0.08] bg-black/10"}`}>
            <div className="grid grid-cols-[minmax(0,1fr)_70px_30px] gap-2"><input aria-label={`No-domain annotation text ${index + 1}`} value={annotation.text} onChange={(event) => onFreeAnnotationsChange(freeAnnotations.map((item) => item.id === annotation.id ? { ...item, text: event.target.value } : item))} className={inputClass} /><input aria-label={`No-domain annotation page ${index + 1}`} type="number" min={1} max={Math.max(1, (parsed.pages?.length ?? 1) - 1)} value={annotation.page} onChange={(event) => onFreeAnnotationsChange(freeAnnotations.map((item) => item.id === annotation.id ? { ...item, page: Math.max(1, Number(event.target.value) || 1) } : item))} className={inputClass} /><button type="button" aria-label={`Remove no-domain annotation ${index + 1}`} onClick={() => onFreeAnnotationsChange(freeAnnotations.filter((item) => item.id !== annotation.id))} className="text-rose-300"><Trash2 size={13} /></button></div>
            <div className="mt-2 grid grid-cols-[minmax(0,1fr)_68px_42px_42px] gap-2"><select aria-label={`No-domain annotation font ${index + 1}`} value={annotation.font_family} onChange={(event) => onFreeAnnotationsChange(freeAnnotations.map((item) => item.id === annotation.id ? { ...item, font_family: event.target.value as ACRFFreeAnnotation["font_family"] } : item))} className={inputClass}>{ACRF_FONT_FAMILIES.map((font) => <option key={font}>{font}</option>)}</select><input aria-label={`No-domain annotation font size ${index + 1}`} type="number" min={6} max={18} value={annotation.font_size} onChange={(event) => onFreeAnnotationsChange(freeAnnotations.map((item) => item.id === annotation.id ? { ...item, font_size: Math.min(18, Math.max(6, Number(event.target.value) || 9)) } : item))} className={inputClass} /><input aria-label={`No-domain annotation text color ${index + 1}`} type="color" value={annotation.text_color} onChange={(event) => onFreeAnnotationsChange(freeAnnotations.map((item) => item.id === annotation.id ? { ...item, text_color: event.target.value.toUpperCase() } : item))} className="h-9 w-10 bg-transparent" /><input aria-label={`No-domain annotation background color ${index + 1}`} type="color" value={annotation.fill_color} onChange={(event) => onFreeAnnotationsChange(freeAnnotations.map((item) => item.id === annotation.id ? { ...item, fill_color: event.target.value.toUpperCase() } : item))} className="h-9 w-10 bg-transparent" /></div>
          </div>)}
        </article>
        {dataset.variables.map((variable) => {
          const variableKey = `${dataset.domain}.${variable.name}`;
          const annotations = variable.acrf_annotations ?? [];
          return <article key={variableKey} className="rounded-lg border border-white/[0.08] bg-white/[0.02] p-2.5">
            <div className="flex items-center justify-between gap-2"><div><span className="font-mono text-xs font-bold text-zinc-200">{variableKey}</span><span className="ml-2 text-[9px] uppercase text-zinc-600">{annotations.length} annotation{annotations.length === 1 ? "" : "s"}</span></div><button type="button" onClick={() => { const next = [...annotations, { source_label: "", mapping_text: variableKey }]; onAnnotationsChange(dataset.domain, variable.name, next); setSelectedAnnotation(acrfAnnotationKey(dataset.domain, variable.name, next.length - 1)); }} className="text-[10px] font-bold text-violet-300"><Plus size={11} className="mr-1 inline" />Add</button></div>
            {!annotations.length && <p className="mt-2 rounded-md border border-dashed border-white/10 p-2 text-[10px] text-zinc-600">No aCRF annotation for this variable.</p>}
            {annotations.map((annotation, index) => {
              const key = acrfAnnotationKey(dataset.domain, variable.name, index);
              const saved = savedAnnotations.get(key);
              const pending = annotation.source_label.trim() !== (saved?.label ?? "").trim() || annotation.mapping_text.trim() !== (saved?.mapping_text ?? variableKey).trim() || stylePending;
              const status = pending ? "pending rebuild" : saved?.status ?? "not built";
              const statusClass = pending ? "text-sky-300" : status === "matched" ? "text-emerald-300" : status === "ambiguous" ? "text-amber-300" : "text-rose-300";
              return <div key={key} ref={(node) => { if (node) editorRefs.current.set(key, node); else editorRefs.current.delete(key); }} className={`mt-2 rounded-md border p-2 ${selectedAnnotation === key ? "border-violet-400 bg-violet-500/[0.08]" : "border-white/[0.08] bg-black/10"}`}>
                <div className="flex items-center justify-between"><span className="text-[9px] font-black uppercase tracking-wider text-zinc-500">Annotation {index + 1}</span><span className={`text-[9px] font-black uppercase ${statusClass}`}>{status}</span></div>
                <label className="mt-2 block"><span className="mb-1 block text-[9px] text-zinc-600">CRF question text</span><input aria-label={`CRF question text for ${variableKey} annotation ${index + 1}`} value={annotation.source_label} onChange={(event) => onAnnotationsChange(dataset.domain, variable.name, annotations.map((item, itemIndex) => itemIndex === index ? { ...item, source_label: event.target.value } : item))} placeholder="Exact question text from blank CRF" className={inputClass} /></label>
                <label className="mt-2 block"><span className="mb-1 block text-[9px] text-zinc-600">Mapping text</span><input aria-label={`aCRF mapping text for ${variableKey} annotation ${index + 1}`} value={annotation.mapping_text} onChange={(event) => onAnnotationsChange(dataset.domain, variable.name, annotations.map((item, itemIndex) => itemIndex === index ? { ...item, mapping_text: event.target.value } : item))} placeholder={variableKey} className={inputClass} /></label>
                <div className="mt-2 flex items-center justify-between"><span className="text-[10px] text-zinc-600">{saved?.page ? `Page ${saved.page}${annotation.x != null ? " - custom position" : ""}` : annotation.source_label.trim() ? "Save to locate question" : "Question required"}</span><div className="flex gap-2">{saved?.page && <button type="button" onClick={() => selectAnnotation(saved)} className="text-[10px] font-bold text-violet-300">Show</button>}<button type="button" aria-label={`Remove ${variableKey} annotation ${index + 1}`} onClick={() => { onAnnotationsChange(dataset.domain, variable.name, annotations.filter((_, itemIndex) => itemIndex !== index)); setSelectedAnnotation(null); }} className="text-[10px] font-bold text-rose-300"><Trash2 size={11} className="mr-1 inline" />Remove</button></div></div>
              </div>;
            })}
          </article>;
        })}
      </div>
    </aside>
    <ACRFPageReview pdf={pdf} pages={parsed.pages ?? []} annotations={parsed.annotations ?? []} selected={selectedAnnotation} pageRefs={pageRefs} onSelect={selectAnnotation} onMove={moveAnnotation} />
  </div>;
}

function ACRFPageReview({ pdf, pages, annotations, selected, pageRefs, onSelect, onMove }: { pdf: Artifact; pages: ACRFPage[]; annotations: ACRFDiagnosticAnnotation[]; selected: string | null; pageRefs: MutableRefObject<Map<number, HTMLDivElement>>; onSelect: (annotation: ACRFDiagnosticAnnotation) => void; onMove: (annotation: ACRFDiagnosticAnnotation, position: ACRFPosition) => void }) {
  if (!pages.length) return <div className="relative"><iframe title="Annotated CRF review" src={api.artifactPreviewUrl(pdf.download_url)} className="h-[48rem] w-full rounded-lg border border-white/10 bg-white" /><p className="absolute bottom-3 left-1/2 -translate-x-1/2 rounded-full bg-zinc-950/90 px-3 py-1.5 text-[10px] text-amber-200">Rebuild once to enable click-to-edit annotations.</p></div>;
  return <div className="h-[48rem] overflow-auto rounded-lg border border-white/10 bg-zinc-800 p-3" aria-label="Clickable annotated CRF review">
    <div className="mx-auto max-w-4xl space-y-4">{pages.map((page) => <div key={page.page} ref={(node) => { if (node) pageRefs.current.set(page.page, node); else pageRefs.current.delete(page.page); }} className="relative overflow-hidden bg-white shadow-xl">
      <img src={api.artifactPageUrl(pdf.download_url, page.page)} alt={`Annotated CRF page ${page.page}`} className="block h-auto w-full" loading="lazy" />
      {annotations.filter((annotation) => annotation.page === page.page && annotation.textbox).map((annotation) => {
        return <DraggableACRFOverlay key={annotation.annotation_id ?? acrfEditorKey(annotation)} page={page} annotation={annotation} selected={selected === acrfEditorKey(annotation)} onSelect={() => onSelect(annotation)} onMove={(position) => onMove(annotation, position)} />;
      })}
    </div>)}</div>
  </div>;
}

function DraggableACRFOverlay({ page, annotation, selected, onSelect, onMove }: { page: ACRFPage; annotation: ACRFDiagnosticAnnotation; selected: boolean; onSelect: () => void; onMove: (position: ACRFPosition) => void }) {
  const [draft, setDraft] = useState<[number, number] | null>(null);
  const draftRef = useRef<[number, number] | null>(null);
  const drag = useRef<{ offsetX: number; offsetY: number; width: number; height: number } | null>(null);
  const [x0, y0, x1, y1] = annotation.textbox!;
  useEffect(() => { setDraft(null); draftRef.current = null; }, [x0, y0]);
  const position = draft ?? [x0, y0];
  const move = (event: ReactPointerEvent<HTMLButtonElement>) => {
    if (!drag.current) return;
    const bounds = event.currentTarget.parentElement?.getBoundingClientRect();
    if (!bounds?.width || !bounds.height) return;
    const pointerX = (event.clientX - bounds.left) / bounds.width * page.width;
    const pointerY = (event.clientY - bounds.top) / bounds.height * page.height;
    const next: [number, number] = [Math.min(Math.max(0, pointerX - drag.current.offsetX), page.width - drag.current.width), Math.min(Math.max(0, pointerY - drag.current.offsetY), page.height - drag.current.height)];
    draftRef.current = next;
    setDraft(next);
  };
  const label = annotation.annotation_type === "domain" ? `${annotation.domain} domain annotation` : annotation.annotation_type === "free" ? `no-domain annotation ${annotation.mapping_text}` : `${annotation.domain}.${annotation.variable} annotation ${annotation.annotation_index + 1}`;
  return <button type="button" aria-label={`Edit and move ${label}`} title={`Drag to move; click to edit ${annotation.mapping_text}`} onClick={onSelect} onPointerDown={(event) => { onSelect(); const bounds = event.currentTarget.parentElement?.getBoundingClientRect(); if (!bounds?.width || !bounds.height) return; event.currentTarget.setPointerCapture?.(event.pointerId); const pointerX = (event.clientX - bounds.left) / bounds.width * page.width; const pointerY = (event.clientY - bounds.top) / bounds.height * page.height; drag.current = { offsetX: pointerX - position[0], offsetY: pointerY - position[1], width: x1 - x0, height: y1 - y0 }; }} onPointerMove={move} onPointerUp={(event) => { move(event); const next = draftRef.current; drag.current = null; if (next) onMove({ page: page.page, x: Math.round(next[0] * 100) / 100, y: Math.round(next[1] * 100) / 100 }); }} className={`absolute cursor-move touch-none rounded transition hover:bg-violet-400/15 hover:ring-2 hover:ring-violet-400 ${selected ? "bg-violet-400/15 ring-2 ring-violet-400" : "bg-transparent"}`} style={{ left: `${position[0] / page.width * 100}%`, top: `${position[1] / page.height * 100}%`, width: `${(x1 - x0) / page.width * 100}%`, height: `${(y1 - y0) / page.height * 100}%` }} />;
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

function DomainTabs({ datasets, selected, onSelect, feedbackCounts }: { datasets: SDTMDataset[]; selected: string; onSelect: (domain: string) => void; feedbackCounts?: Map<string, number> }) {
  return <div className="flex flex-wrap gap-2">{datasets.map((dataset) => <button type="button" key={dataset.domain} onClick={() => onSelect(dataset.domain)} className={`focus-ring rounded-lg border px-3 py-2 font-mono text-xs font-bold ${selected === dataset.domain ? "border-violet-500/40 bg-violet-500/10 text-violet-200" : "border-white/10 bg-white/[0.02] text-zinc-500"}`}>{dataset.domain}{feedbackCounts?.has(dataset.domain) && <span className="ml-2 rounded-full bg-amber-400/15 px-1.5 py-0.5 text-[9px] text-amber-200">{feedbackCounts.get(dataset.domain)}</span>}</button>)}</div>;
}

type ProgramLanguage = "r" | "sas";
type SyntaxTokenKind = "plain" | "comment" | "string" | "keyword" | "number" | "function" | "operator" | "macro";
type SyntaxToken = { kind: SyntaxTokenKind; text: string };

const R_KEYWORDS = new Set(["break", "else", "FALSE", "for", "function", "if", "in", "Inf", "NA", "NaN", "next", "NULL", "repeat", "TRUE", "while"]);
const SAS_KEYWORDS = new Set(["and", "array", "as", "by", "case", "create", "data", "delete", "do", "drop", "else", "end", "first", "format", "from", "full", "group", "having", "if", "in", "infile", "inner", "input", "join", "keep", "last", "left", "length", "merge", "missing", "not", "on", "or", "order", "otherwise", "output", "proc", "quit", "rename", "retain", "right", "run", "select", "set", "table", "then", "when", "where"]);

function DomainProgramReview({ jobId, domain, artifacts, editable }: { jobId?: string; domain: string; artifacts: Artifact[]; editable: boolean }) {
  const client = useQueryClient();
  const slug = domain.trim().replace(/[^A-Za-z0-9]+/g, "-").replace(/^-+|-+$/g, "").toLowerCase();
  const rArtifact = artifacts.find((artifact) => artifact.name.toLowerCase() === `build-${slug}.r`);
  const sasArtifact = artifacts.find((artifact) => artifact.name.toLowerCase() === `build-${slug}.sas`);
  const [language, setLanguage] = useState<ProgramLanguage>(rArtifact ? "r" : "sas");
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  useEffect(() => setLanguage(rArtifact ? "r" : "sas"), [domain, rArtifact?.id, sasArtifact?.id]);
  const rQuery = useQuery({ queryKey: ["sdtm-program", rArtifact?.id, rArtifact?.sha256], queryFn: () => api.artifactText(rArtifact!.download_url), enabled: Boolean(rArtifact) });
  const sasQuery = useQuery({ queryKey: ["sdtm-program", sasArtifact?.id, sasArtifact?.sha256], queryFn: () => api.artifactText(sasArtifact!.download_url), enabled: Boolean(sasArtifact) });
  const artifact = language === "r" ? rArtifact : sasArtifact;
  const query = language === "r" ? rQuery : sasQuery;
  useEffect(() => {
    if (!editing && query.data !== undefined) setDraft(query.data);
  }, [editing, language, query.data]);
  const mutation = useMutation({
    mutationFn: () => api.updateSdtmProgram(jobId!, domain, language, draft, artifact!.sha256),
    onSuccess: (job) => {
      client.setQueryData(["job", jobId], job);
      client.setQueryData(["sdtm-program", artifact?.id, artifact?.sha256], draft);
      setEditing(false);
    },
  });
  const selectLanguage = (next: ProgramLanguage) => {
    setEditing(false);
    mutation.reset();
    setLanguage(next);
  };

  if (!rArtifact && !sasArtifact) {
    return <EmptyReview text={`Generated R/SAS program artifacts are unavailable for ${domain}. Save or rerun the reviewed mapping to build them.`} />;
  }
  return <article className="overflow-hidden rounded-xl border border-white/10 bg-[#111113]">
    <header className="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 p-4">
      <div><p className="font-mono text-sm font-black text-violet-200">{artifact?.name}</p><p className="mt-1 text-[11px] text-zinc-600">Exact reviewed artifact{artifact ? ` · SHA-256 ${artifact.sha256.slice(0, 12)}…` : ""}</p></div>
      <div className="flex flex-wrap items-center gap-2">
        <div role="tablist" aria-label={`${domain} program languages`} className="flex rounded-lg border border-white/10 bg-black/20 p-1">
          {(["r", "sas"] as const).map((item) => {
            const available = item === "r" ? Boolean(rArtifact) : Boolean(sasArtifact);
            return <button key={item} type="button" role="tab" aria-selected={language === item} disabled={!available || mutation.isPending} onClick={() => selectLanguage(item)} className={`rounded-md px-3 py-1.5 text-[10px] font-black uppercase tracking-wider ${language === item ? "bg-violet-500/20 text-violet-200" : available ? "text-zinc-500 hover:text-zinc-300" : "cursor-not-allowed text-zinc-800"}`}>{item === "r" ? "R" : "SAS"}</button>;
          })}
        </div>
        {artifact && jobId && editable && !editing && <Button type="button" variant="outline" size="sm" disabled={query.isPending} onClick={() => { setDraft(query.data ?? ""); setEditing(true); }}><Code2 size={14} />Edit {language.toUpperCase()}</Button>}
        {artifact && jobId && editable && editing && <><Button type="button" variant="outline" size="sm" disabled={mutation.isPending} onClick={() => { setDraft(query.data ?? ""); setEditing(false); mutation.reset(); }}>Cancel</Button><Button type="button" variant="clinical" size="sm" disabled={mutation.isPending || !draft.trim() || draft === query.data} onClick={() => mutation.mutate()}><Save size={14} />{mutation.isPending ? "Saving…" : `Save ${language.toUpperCase()}`}</Button></>}
        {artifact && <Button asChild type="button" variant="outline" size="sm"><a href={api.artifactUrl(artifact.download_url)}><Download size={14} />Download</a></Button>}
      </div>
    </header>
    <div className="p-4">
      {query.isPending ? <EmptyReview text={`Loading ${domain} ${language.toUpperCase()} program…`} /> : query.isError ? <div className="rounded-lg border border-rose-500/20 bg-rose-500/10 p-4 text-sm text-rose-300">{query.error.message}</div> : editing ? <SyntaxHighlightedProgramEditor code={draft} language={language} label={`${domain} ${language.toUpperCase()} code editor`} onChange={setDraft} /> : <SyntaxHighlightedProgram code={query.data ?? ""} language={language} label={`${domain} ${language.toUpperCase()} program`} />}
      {mutation.error && <p className="mt-3 text-xs text-rose-300">{mutation.error.message}</p>}
      {editing && <p className="mt-3 text-[11px] leading-5 text-amber-200">Saving replaces this reviewed artifact, records an audit entry, and marks prior execution and validation results as historical. R still runs only in the isolated runner; SAS remains export-only.</p>}
    </div>
  </article>;
}

function SyntaxHighlightedProgram({ code, language, label }: { code: string; language: ProgramLanguage; label: string }) {
  const lines = highlightedProgramLines(code, language);
  return <pre className="max-h-[48rem] overflow-auto rounded-lg border border-white/10 bg-[#08090c] py-3 font-mono text-xs leading-5 text-zinc-300"><code aria-label={label}>{lines.map((tokens, lineIndex) => <span className="block min-w-max px-3" key={lineIndex}><span aria-hidden="true" className="mr-4 inline-block w-9 select-none border-r border-white/[0.07] pr-3 text-right text-zinc-700">{lineIndex + 1}</span>{tokens.length ? tokens.map((token, tokenIndex) => <span data-token={token.kind} className={tokenClass(token.kind)} key={`${lineIndex}-${tokenIndex}`}>{token.text}</span>) : "\u00a0"}</span>)}</code></pre>;
}

function SyntaxHighlightedProgramEditor({ code, language, label, onChange }: { code: string; language: ProgramLanguage; label: string; onChange: (code: string) => void }) {
  const highlight = useRef<HTMLPreElement>(null);
  const lines = highlightedProgramLines(code, language);
  return <div className="relative h-[36rem] overflow-hidden rounded-lg border border-white/10 bg-[#08090c] focus-within:border-violet-500/50 focus-within:ring-1 focus-within:ring-violet-500/20">
    <pre ref={highlight} aria-hidden="true" data-testid={`${label} syntax highlighting`} style={{ tabSize: 2, scrollbarWidth: "none" }} className="pointer-events-none absolute inset-0 overflow-auto whitespace-pre p-3 font-mono text-xs leading-5 text-zinc-300 [&::-webkit-scrollbar]:hidden"><code>{lines.map((tokens, lineIndex) => <span key={lineIndex}>{tokens.map((token, tokenIndex) => <span data-token={token.kind} className={tokenClass(token.kind)} key={`${lineIndex}-${tokenIndex}`}>{token.text}</span>)}{lineIndex < lines.length - 1 ? "\n" : null}</span>)}</code></pre>
    <textarea
      aria-label={label}
      value={code}
      onChange={(event) => onChange(event.target.value)}
      onScroll={(event) => {
        if (!highlight.current) return;
        highlight.current.scrollTop = event.currentTarget.scrollTop;
        highlight.current.scrollLeft = event.currentTarget.scrollLeft;
      }}
      wrap="off"
      spellCheck={false}
      style={{ tabSize: 2 }}
      className="absolute inset-0 h-full w-full resize-none overflow-auto whitespace-pre border-0 bg-transparent p-3 font-mono text-xs leading-5 text-transparent caret-zinc-100 outline-none selection:bg-violet-500/40 selection:text-transparent"
    />
  </div>;
}

function highlightedProgramLines(code: string, language: ProgramLanguage): SyntaxToken[][] {
  let inBlockComment = false;
  return code.replace(/\r\n?/g, "\n").split("\n").map((line) => {
    const result = tokenizeProgramLine(line, language, inBlockComment);
    inBlockComment = result.inBlockComment;
    return result.tokens;
  });
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
    datasets: arrayValue<SDTMDataset>(value.datasets).map((dataset) => {
      const rawVariables = arrayValue<SDTMVariable>(dataset.variables);
      const legacyStyle = rawVariables.find((variable) => variable.acrf_font_family || variable.acrf_font_size || variable.acrf_text_color || variable.acrf_fill_color);
      const variables = rawVariables.map((variable) => {
        const normalized = normalizeVariable(variable);
        const annotations = normalized.acrf_annotations?.length ? normalized.acrf_annotations : normalized.crf_source_label ? [{ source_label: normalized.crf_source_label, mapping_text: `${dataset.domain}.${normalized.name}` }] : [];
        return { ...normalized, acrf_annotations: annotations };
      });
      const rawDomainAnnotation = dataset.acrf_domain_annotation;
      const domainAnnotation: ACRFDomainAnnotation = {
        enabled: rawDomainAnnotation?.enabled !== false,
        text: stringValue(rawDomainAnnotation?.text, dataset.domain),
        positions: arrayValue<ACRFPosition>(rawDomainAnnotation?.positions).filter((item) => finiteNumber(item.page) && finiteNumber(item.x) && finiteNumber(item.y)).map((item) => ({ page: item.page, x: item.x, y: item.y })),
      };
      return { ...dataset, review_assumptions: arrayValue<string>(dataset.review_assumptions), review_unresolved_mappings: arrayValue<string>(dataset.review_unresolved_mappings), acrf_font_family: dataset.acrf_font_family ?? legacyStyle?.acrf_font_family ?? "Helvetica", acrf_font_size: dataset.acrf_font_size ?? legacyStyle?.acrf_font_size ?? 8, acrf_text_color: dataset.acrf_text_color ?? legacyStyle?.acrf_text_color ?? "#141F3D", acrf_fill_color: dataset.acrf_fill_color ?? legacyStyle?.acrf_fill_color ?? "#EBF2FF", acrf_domain_annotation: domainAnnotation, record_plan: normalizeRecordPlan(dataset.record_plan), variables };
    }),
    rule_augmentations: arrayValue<VariableRule>(value.rule_augmentations),
    acrf_free_annotations: arrayValue<ACRFFreeAnnotation>(value.acrf_free_annotations).map((item, index) => ({ id: stringValue(item.id, `free-${index + 1}`), text: stringValue(item.text, ""), page: finiteNumber(item.page) ? item.page : 1, x: finiteNumber(item.x) ? item.x : 48, y: finiteNumber(item.y) ? item.y : 48, font_family: ACRF_FONT_FAMILIES.includes(item.font_family) ? item.font_family : "Helvetica Bold", font_size: finiteNumber(item.font_size) ? item.font_size : 9, text_color: stringValue(item.text_color, "#7F1D1D").toUpperCase(), fill_color: stringValue(item.fill_color, "#FEE2E2").toUpperCase() })),
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
  plan.acrf_free_annotations.forEach((annotation, index) => { if (!annotation.text.trim()) issues.push(`No-domain aCRF annotation ${index + 1} needs text.`); if (annotation.page < 1) issues.push(`No-domain aCRF annotation ${index + 1} needs a valid page.`); });
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
      variable.acrf_annotations?.forEach((annotation, index) => { if (!annotation.source_label.trim()) issues.push(`${dataset.domain}.${variable.name} annotation ${index + 1} needs CRF question text.`); });
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
    review_assumptions: [],
    review_unresolved_mappings: [],
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
function finiteNumber(value: unknown): value is number { return typeof value === "number" && Number.isFinite(value); }
function encodePatchSelector(value: string): string { return value.replaceAll("~", "~0").replaceAll("/", "~1"); }
function allowsSourcelessOrigin(value: string): boolean { const normalized = value.trim().toLowerCase(); return ["assigned", "derived", "protocol", "system", "sponsor"].some((token) => normalized.includes(token)); }
function splitLines(value: string): string[] { return value.split("\n").map((item) => item.trim()).filter(Boolean); }
