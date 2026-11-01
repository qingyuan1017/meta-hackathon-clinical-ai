"use client";

import { useMemo, useState, type DragEvent, type ReactNode } from "react";
import { AlertTriangle, ArrowRight, Database, GripVertical, Plus, Save, Table2, Trash2 } from "lucide-react";
import type { Job } from "@/lib/types";
import type { RevisionFeedbackEvent } from "@/lib/revision-decision";
import { groupOperationsByDomain, ReviewPatchPanel } from "./review-patch-panel";
import { RevisionDecisionPanel } from "./revision-decision-panel";
import { Button } from "./ui/button";
import {
  VariableMappingMatrix,
  newSourceVariable,
  normalizeVariable,
  vlmMatrixIssues,
  type SDTMVariableDraft,
  type SourceInventoryDataset,
} from "./sdtm-lineage-editor";

type SourceType = "raw" | "sdtm";
type Relationship = "direct" | "stack" | "join" | "split" | "derived";

interface SourceDataset extends SourceInventoryDataset { label: string; source_type: SourceType; }
interface SourceSpecification { study_name: string; datasets: SourceDataset[]; }
interface DomainMapping { source_dataset: string; source_type: SourceType; target_domain: string; relationship: Relationship; rationale: string; }
interface UnmappedDataset { source_dataset: string; rationale: string; }

export interface SDTMDomainMappingPlanDraft extends Record<string, unknown> {
  study_name: string;
  standard: string;
  domain_mappings: DomainMapping[];
  unmapped_datasets: UnmappedDataset[];
  assumptions: string[];
  unresolved_mappings: string[];
}

type SDTMVariable = SDTMVariableDraft;

interface SDTMDataset {
  domain: string;
  description: string;
  structure: string;
  key_variables: string[];
  variables: SDTMVariable[];
  review_assumptions: string[];
  review_unresolved_mappings: string[];
}

export interface SDTMVariableMappingPlanDraft extends Record<string, unknown> {
  study_name: string;
  standard: string;
  define_standard: string;
  datasets: SDTMDataset[];
  assumptions: string[];
  unresolved_mappings: string[];
}

interface DomainReviewEnvelope { source_spec: SourceSpecification; domain_mapping: SDTMDomainMappingPlanDraft; }
interface VariableReviewEnvelope extends DomainReviewEnvelope { variable_mapping: SDTMVariableMappingPlanDraft; }

const inputClass = "focus-ring min-h-9 w-full rounded-md border border-white/10 bg-[#101012] px-2.5 py-2 text-xs text-zinc-200 placeholder:text-zinc-600";

export function SDTMDomainMappingReview({ value, onChange, onApprove, saving, error, reviewJob }: {
  value: Record<string, unknown>;
  onChange: (value: Record<string, unknown>) => void;
  onApprove: (value: SDTMDomainMappingPlanDraft) => void;
  saving: boolean;
  error?: string | null;
  reviewJob?: Job;
}) {
  const envelope = normalizeDomainEnvelope(value);
  const plan = envelope.domain_mapping;
  const [newDomain, setNewDomain] = useState("");
  const [extraDomains, setExtraDomains] = useState<string[]>([]);
  const domains = useMemo(() => Array.from(new Set([...plan.domain_mappings.map((item) => item.target_domain), ...extraDomains])).filter(Boolean), [extraDomains, plan.domain_mappings]);
  const issues = domainIssues(envelope);
  const update = (mutate: (next: SDTMDomainMappingPlanDraft) => void) => {
    const nextPlan = structuredClone(plan);
    mutate(nextPlan);
    onChange({ ...value, source_spec: envelope.source_spec, domain_mapping: nextPlan });
  };
  const mapSource = (source: SourceDataset, targetDomain: string) => update((next) => {
    if (next.domain_mappings.some((item) => item.source_dataset === source.name && item.target_domain === targetDomain)) return;
    next.unmapped_datasets = next.unmapped_datasets.filter((item) => item.source_dataset !== source.name);
    next.domain_mappings.push({ source_dataset: source.name, source_type: source.source_type, target_domain: targetDomain, relationship: "direct", rationale: "User-reviewed dataset mapping" });
  });
  const markNotMapped = (source: SourceDataset) => update((next) => {
    next.domain_mappings = next.domain_mappings.filter((item) => item.source_dataset !== source.name);
    if (!next.unmapped_datasets.some((item) => item.source_dataset === source.name)) {
      next.unmapped_datasets.push({ source_dataset: source.name, rationale: "" });
    }
  });
  const onDrop = (event: DragEvent, targetDomain: string) => {
    event.preventDefault();
    const source = envelope.source_spec.datasets.find((item) => item.name === event.dataTransfer.getData("text/x-sdtm-source"));
    if (source) mapSource(source, targetDomain);
  };
  const addDomain = () => {
    const domain = newDomain.trim().toUpperCase();
    if (domain && !domains.includes(domain)) setExtraDomains((current) => [...current, domain]);
    setNewDomain("");
  };

  return <div className="space-y-5">
    <ReviewGateHeader step="2 of 3" title="Domain mapping review required" description="Confirm each normalized source is either assigned to the correct target SDTM domain or explicitly marked not mapped with a rationale. Variable mapping will not start until you approve these dispositions." />
    <div className="grid gap-4 md:grid-cols-2">
      <label><EditorLabel>Study</EditorLabel><input value={plan.study_name} onChange={(event) => update((next) => { next.study_name = event.target.value; })} className={inputClass} /></label>
      <label><EditorLabel>Target standard</EditorLabel><input value={plan.standard} onChange={(event) => update((next) => { next.standard = event.target.value; })} className={inputClass} /></label>
    </div>
    <div className="grid gap-5 xl:grid-cols-[290px_minmax(0,1fr)]">
      <section className="rounded-xl border border-white/10 bg-[#141416] p-4">
        <p className="text-xs font-black uppercase tracking-[0.12em] text-zinc-400">Approved source inventory</p>
        <p className="mt-1 text-xs leading-5 text-zinc-600">Drag applicable sources onto one or more domains, or mark them not mapped.</p>
        <div className="mt-4 space-y-2">{envelope.source_spec.datasets.map((source) => {
          const isMapped = plan.domain_mappings.some((item) => item.source_dataset === source.name);
          const isNotMapped = plan.unmapped_datasets.some((item) => item.source_dataset === source.name);
          return <div key={source.name} draggable={!isNotMapped} onDragStart={(event) => { event.dataTransfer.setData("text/x-sdtm-source", source.name); event.dataTransfer.effectAllowed = "copy"; }} className="rounded-lg border border-white/10 bg-white/[0.03] p-3"><div className="flex items-center gap-3"><GripVertical size={15} className="text-zinc-600" /><div className="min-w-0 flex-1"><p className="font-mono text-xs font-bold text-violet-200">{source.name}</p><p className="mt-1 truncate text-[10px] text-zinc-500">{source.source_type.toUpperCase()} · {source.label}</p></div><span className={`text-[9px] font-black uppercase tracking-wider ${isMapped ? "text-emerald-300" : isNotMapped ? "text-amber-300" : "text-zinc-600"}`}>{isMapped ? "Mapped" : isNotMapped ? "Not mapped" : "Needs review"}</span></div><button type="button" aria-label={`Mark ${source.name} not mapped`} onClick={() => markNotMapped(source)} disabled={isNotMapped} className="mt-2 w-full rounded-md border border-white/10 px-2 py-1.5 text-[10px] font-bold text-zinc-400 hover:border-amber-500/30 hover:text-amber-200 disabled:cursor-default disabled:opacity-40">Mark not mapped</button></div>;
        })}</div>
      </section>
      <section className="space-y-3">
        <RelationshipGuide />
        <div className="flex gap-2 rounded-xl border border-white/10 bg-white/[0.02] p-3"><input aria-label="New target domain" value={newDomain} onChange={(event) => setNewDomain(event.target.value.toUpperCase())} onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); addDomain(); } }} placeholder="Add target domain, e.g. DM" className={inputClass} /><Button type="button" variant="outline" onClick={addDomain}><Plus size={14} />Domain</Button></div>
        {domains.map((domain) => {
          const mappings = plan.domain_mappings.map((mapping, index) => ({ mapping, index })).filter(({ mapping }) => mapping.target_domain === domain);
          return <article key={domain} onDragOver={(event) => event.preventDefault()} onDrop={(event) => onDrop(event, domain)} className="rounded-xl border border-dashed border-violet-500/25 bg-violet-500/[0.035] p-4">
            <div className="flex items-center justify-between"><div><p className="font-mono text-sm font-black text-violet-200">{domain}</p><p className="mt-1 text-xs text-zinc-600">Drop source datasets here</p></div><Database size={18} className="text-violet-400" /></div>
            <div className="mt-3 space-y-2">{mappings.map(({ mapping, index }) => <div key={`${mapping.source_dataset}-${index}`} className="grid gap-2 rounded-lg border border-white/10 bg-[#141416] p-3 lg:grid-cols-[150px_120px_130px_minmax(180px,1fr)_36px]">
              <div className="flex items-center gap-2 font-mono text-xs font-bold text-zinc-200">{mapping.source_dataset}<ArrowRight size={13} className="text-zinc-600" /></div>
              <select value={mapping.source_type} disabled className={`${inputClass} opacity-70`}><option value="raw">Raw</option><option value="sdtm">SDTM</option></select>
              <select aria-label={`${mapping.source_dataset} to ${domain} relationship`} value={mapping.relationship} onChange={(event) => update((next) => { next.domain_mappings[index].relationship = event.target.value as Relationship; })} className={inputClass}>{["direct", "stack", "join", "split", "derived"].map((item) => <option key={item} value={item}>{item[0].toUpperCase() + item.slice(1)}</option>)}</select>
              <input value={mapping.rationale} onChange={(event) => update((next) => { next.domain_mappings[index].rationale = event.target.value; })} placeholder="Mapping rationale" className={inputClass} />
              <button type="button" aria-label={`Remove ${mapping.source_dataset} to ${domain}`} onClick={() => update((next) => { next.domain_mappings.splice(index, 1); })} className="grid h-9 w-9 place-items-center rounded-md text-zinc-600 hover:bg-rose-500/10 hover:text-rose-300"><Trash2 size={14} /></button>
            </div>)}{!mappings.length && <p className="rounded-lg border border-dashed border-white/10 p-4 text-center text-xs text-zinc-600">No source assigned yet.</p>}</div>
            {reviewJob?.review_patch && <ReviewPatchPanel job={reviewJob} domain={domain} />}
          </article>;
        })}
        <article className="rounded-xl border border-dashed border-amber-500/25 bg-amber-500/[0.035] p-4">
          <div><p className="text-sm font-black text-amber-200">Not mapped to SDTM</p><p className="mt-1 text-xs text-zinc-600">These sources were considered and intentionally excluded from SDTM mapping.</p></div>
          <div className="mt-3 space-y-2">{plan.unmapped_datasets.map((item, index) => <div key={item.source_dataset} className="grid gap-2 rounded-lg border border-white/10 bg-[#141416] p-3 lg:grid-cols-[160px_minmax(220px,1fr)_36px]"><span className="self-center font-mono text-xs font-bold text-amber-200">{item.source_dataset}</span><input aria-label={`Reason ${item.source_dataset} is not mapped`} value={item.rationale} onChange={(event) => update((next) => { next.unmapped_datasets[index].rationale = event.target.value; })} placeholder="Why this source does not contribute to SDTM" className={inputClass} /><button type="button" aria-label={`Restore ${item.source_dataset} to review`} onClick={() => update((next) => { next.unmapped_datasets.splice(index, 1); })} className="grid h-9 w-9 place-items-center rounded-md text-zinc-600 hover:bg-amber-500/10 hover:text-amber-200"><Trash2 size={14} /></button></div>)}{!plan.unmapped_datasets.length && <p className="rounded-lg border border-dashed border-white/10 p-4 text-center text-xs text-zinc-600">No sources are currently marked not mapped.</p>}</div>
          {reviewJob?.review_patch && <ReviewPatchPanel job={reviewJob} domain="Not mapped" />}
        </article>
      </section>
    </div>
    {reviewJob?.review_patch && <ReviewPatchPanel job={reviewJob} domain="General" />}
    <ReviewNotes assumptions={plan.assumptions} unresolved={plan.unresolved_mappings} onAssumptions={(items) => update((next) => { next.assumptions = items; })} onUnresolved={(items) => update((next) => { next.unresolved_mappings = items; })} />
    <ApprovalBar issues={issues} error={error} saving={saving} readyText="All normalized datasets have a reviewed mapping disposition." actionText="Approve domains and build variable mapping" onApprove={() => onApprove(plan)} />
  </div>;
}

export function SDTMVariableMappingReview({ value, onChange, onApprove, saving, error, reviewJob, feedbackEvents, onReturnToDomainMapping, returningToDomainMapping = false, returnDomainError }: {
  value: Record<string, unknown>;
  onChange: (value: Record<string, unknown>) => void;
  onApprove: (value: SDTMVariableMappingPlanDraft) => void;
  saving: boolean;
  error?: string | null;
  reviewJob?: Job;
  feedbackEvents?: RevisionFeedbackEvent[];
  onReturnToDomainMapping?: () => void;
  returningToDomainMapping?: boolean;
  returnDomainError?: string | null;
}) {
  const envelope = normalizeVariableEnvelope(value);
  const plan = envelope.variable_mapping;
  const [selectedDomain, setSelectedDomain] = useState(plan.datasets[0]?.domain ?? "");
  const [confirmDomainReturn, setConfirmDomainReturn] = useState(false);
  const active = plan.datasets.find((dataset) => dataset.domain === selectedDomain) ?? plan.datasets[0];
  const issues = variableIssues(envelope);
  const update = (mutate: (next: SDTMVariableMappingPlanDraft) => void) => {
    const nextPlan = structuredClone(plan);
    hydrateLegacyReviewNotes(nextPlan, envelope.domain_mapping);
    mutate(nextPlan);
    onChange({ ...value, source_spec: envelope.source_spec, domain_mapping: envelope.domain_mapping, variable_mapping: nextPlan });
  };
  const allowedSources = active ? envelope.domain_mapping.domain_mappings.filter((item) => item.target_domain === active.domain).map((item) => item.source_dataset) : [];
  const feedbackCounts = new Map(
    reviewJob?.review_patch
      ? groupOperationsByDomain(reviewJob.review_patch.operations, recordValue(reviewJob.result)).map((group) => [group.domain, group.operations.length])
      : [],
  );
  const activeProposalOperations = active && reviewJob?.review_patch?.stage === "variable_mapping"
    ? reviewJob.review_patch.operations.filter((operation) => operation.path.includes(`/variable_mapping/datasets/domain=${encodePatchSelector(active.domain)}/`))
    : [];
  const activeAssumptions = active ? domainReviewNotes(plan, envelope.domain_mapping, active.domain, "review_assumptions") : [];
  const activeUnresolved = active ? domainReviewNotes(plan, envelope.domain_mapping, active.domain, "review_unresolved_mappings") : [];
  const stageAssumptions = stageWideReviewNotes(plan, envelope.domain_mapping, "assumptions");
  const stageUnresolved = stageWideReviewNotes(plan, envelope.domain_mapping, "unresolved_mappings");

  return <div className="space-y-5">
    <ReviewGateHeader step="3 of 3" title="Variable and value-level mapping review required" description="Review each SDTM variable row and the VLM cells. Rule augmentation and code generation remain blocked until this matrix is approved." />
    {onReturnToDomainMapping && <div className="rounded-xl border border-white/10 bg-white/[0.025] p-4">
      {!confirmDomainReturn ? <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between"><div><p className="text-sm font-bold text-zinc-200">Need to change a source-to-domain assignment?</p><p className="mt-1 text-xs leading-5 text-zinc-500">Return to the domain gate before approving variable mappings.</p></div><Button type="button" variant="outline" onClick={() => setConfirmDomainReturn(true)}>Change domain mapping</Button></div> : <div role="alert" className="space-y-3"><div><p className="text-sm font-bold text-amber-200">Return to domain mapping review?</p><p className="mt-1 text-xs leading-5 text-amber-100/75">The source inventory and unchanged domain variable mappings will be retained. After you approve the revised domain plan, only added or materially changed domains will be regenerated; removed domains will be dropped. This action does not approve or advance the workflow.</p></div><div className="flex flex-wrap gap-2"><Button type="button" variant="outline" onClick={() => setConfirmDomainReturn(false)} disabled={returningToDomainMapping}>Cancel</Button><Button type="button" variant="clinical" onClick={onReturnToDomainMapping} disabled={returningToDomainMapping}>{returningToDomainMapping ? "Returning…" : "Return to domain mapping"}</Button></div>{returnDomainError && <p className="text-xs text-rose-300">{returnDomainError}</p>}</div>}
    </div>}
    {(stageAssumptions.length > 0 || stageUnresolved.length > 0) && <RevisionDecisionPanel result={{ assumptions: stageAssumptions, unresolved_mappings: stageUnresolved }} events={feedbackEvents} title="Stage-wide feedback decisions" assumptionsTitle="Stage-wide assumptions" ariaLabel="Stage-wide feedback decisions" onlyMatchedFeedback collapsedByDefault />}
    <div className="flex flex-wrap gap-2">{plan.datasets.map((dataset) => <button type="button" key={dataset.domain} onClick={() => setSelectedDomain(dataset.domain)} className={`focus-ring rounded-lg border px-3 py-2 font-mono text-xs font-bold ${active?.domain === dataset.domain ? "border-violet-500/40 bg-violet-500/10 text-violet-200" : "border-white/10 text-zinc-500"}`}>{dataset.domain}{feedbackCounts.has(dataset.domain) && <span className="ml-2 rounded-full bg-amber-400/15 px-1.5 py-0.5 text-[9px] text-amber-200">{feedbackCounts.get(dataset.domain)}</span>}</button>)}</div>
    {active && <section className="overflow-hidden rounded-xl border border-white/10 bg-[#141416]">
      <div className="grid gap-3 border-b border-white/10 p-4 lg:grid-cols-[180px_minmax(240px,1fr)_minmax(260px,1fr)_auto]">
        <label><EditorLabel>Domain</EditorLabel><input value={active.domain} readOnly className={`${inputClass} font-mono font-bold text-violet-200 opacity-70`} /></label>
        <label><EditorLabel>Description</EditorLabel><input value={active.description} onChange={(event) => updateDataset(plan, active.domain, update, "description", event.target.value)} className={inputClass} /></label>
        <label><EditorLabel>Structure</EditorLabel><input value={active.structure} onChange={(event) => updateDataset(plan, active.domain, update, "structure", event.target.value)} className={inputClass} /></label>
        <Button type="button" variant="outline" className="mt-5" onClick={() => update((next) => { const dataset = next.datasets.find((item) => item.domain === active.domain); if (dataset) dataset.variables.push(newSourceVariable("NEWVAR", allowedSources[0] ?? "")); })}><Plus size={14} />Variable</Button>
      </div>
      <div className="space-y-4 p-4">
        <VariableMappingMatrix variables={active.variables} inventory={envelope.source_spec.datasets} allowedDatasets={allowedSources} sourceRelationships={envelope.domain_mapping.domain_mappings.filter((item) => item.target_domain === active.domain).map((item) => ({ dataset: item.source_dataset, relationship: item.relationship }))} domain={active.domain} proposalOperations={activeProposalOperations} onChange={(variables) => updateDataset(plan, active.domain, update, "variables", variables)} />
      </div>
      {(activeAssumptions.length > 0 || activeUnresolved.length > 0) && <div className="border-t border-white/10 p-4"><RevisionDecisionPanel
        result={{ assumptions: activeAssumptions, unresolved_mappings: activeUnresolved }}
        events={feedbackEvents}
        title={`${active.domain} feedback decisions`}
        assumptionsTitle={`${active.domain} assumptions`}
        ariaLabel={`${active.domain} feedback decisions`}
        onlyMatchedFeedback
        collapsedByDefault
      /></div>}
    </section>}
    <ApprovalBar issues={issues} error={error} saving={saving} readyText="Every approved domain has a reviewable variable matrix." actionText="Approve mappings and generate rules/code" onApprove={() => onApprove(plan)} />
  </div>;
}

function ReviewGateHeader({ step, title, description }: { step: string; title: string; description: string }) { return <div className="rounded-xl border border-amber-500/25 bg-amber-500/[0.08] p-4"><p className="text-xs font-black uppercase tracking-[0.14em] text-amber-200">Review gate {step}</p><p className="mt-1 text-base font-bold text-amber-100">{title}</p><p className="mt-1 text-sm leading-6 text-amber-100/75">{description}</p></div>; }
function ReviewNotes({ assumptions, unresolved, onAssumptions, onUnresolved }: { assumptions: string[]; unresolved: string[]; onAssumptions: (items: string[]) => void; onUnresolved: (items: string[]) => void }) { return <section><div className="grid gap-4 md:grid-cols-2"><label><EditorLabel>Assumptions — one per line</EditorLabel><textarea value={assumptions.join("\n")} onChange={(event) => onAssumptions(splitLines(event.target.value))} className={`${inputClass} min-h-28`} /></label><label><EditorLabel>Unresolved mappings — one per line</EditorLabel><textarea value={unresolved.join("\n")} onChange={(event) => onUnresolved(splitLines(event.target.value))} className={`${inputClass} min-h-28`} /></label></div></section>; }
function ApprovalBar({ issues, error, saving, readyText, actionText, onApprove }: { issues: string[]; error?: string | null; saving: boolean; readyText: string; actionText: string; onApprove: () => void }) { return <div className="sticky bottom-3 z-20 flex flex-col gap-3 rounded-xl border border-white/15 bg-[#161619]/95 p-4 shadow-2xl backdrop-blur sm:flex-row sm:items-center sm:justify-between"><div>{issues.length ? <p className="flex items-center gap-2 text-xs font-bold text-amber-200"><AlertTriangle size={15} />{issues[0]}{issues.length > 1 ? ` (+${issues.length - 1} more)` : ""}</p> : <p className="flex items-center gap-2 text-xs font-bold text-emerald-300"><Table2 size={15} />{readyText}</p>}{error && <p className="mt-1 text-xs text-rose-300">{error}</p>}</div><Button type="button" variant="clinical" onClick={onApprove} disabled={saving || issues.length > 0}><Save size={16} />{saving ? "Approving and resuming…" : actionText}</Button></div>; }
function EditorLabel({ children }: { children: ReactNode }) { return <span className="mb-1.5 block text-[10px] font-black uppercase tracking-[0.12em] text-zinc-500">{children}</span>; }

function normalizeDomainEnvelope(value: Record<string, unknown>): DomainReviewEnvelope {
  const source = recordValue(value.source_spec);
  const plan = recordValue(value.domain_mapping);
  return { source_spec: { study_name: stringValue(source.study_name, "Untitled study"), datasets: arrayValue<SourceDataset>(source.datasets).map((dataset) => ({ ...dataset, variables: arrayValue<{ name: string; label?: string }>(dataset.variables) })) }, domain_mapping: { ...plan, study_name: stringValue(plan.study_name, "Untitled study"), standard: stringValue(plan.standard, "SDTMIG 3.4"), domain_mappings: arrayValue<DomainMapping>(plan.domain_mappings), unmapped_datasets: arrayValue<UnmappedDataset>(plan.unmapped_datasets), assumptions: arrayValue<string>(plan.assumptions), unresolved_mappings: arrayValue<string>(plan.unresolved_mappings) } };
}
function normalizeVariableEnvelope(value: Record<string, unknown>): VariableReviewEnvelope {
  const domain = normalizeDomainEnvelope(value);
  const plan = recordValue(value.variable_mapping);
  return { ...domain, variable_mapping: { ...plan, study_name: stringValue(plan.study_name, "Untitled study"), standard: stringValue(plan.standard, "SDTMIG 3.4"), define_standard: stringValue(plan.define_standard, "Define-XML 2.1"), datasets: arrayValue<SDTMDataset>(plan.datasets).map((dataset) => ({ ...dataset, key_variables: arrayValue<string>(dataset.key_variables), review_assumptions: arrayValue<string>(dataset.review_assumptions), review_unresolved_mappings: arrayValue<string>(dataset.review_unresolved_mappings), variables: arrayValue<SDTMVariable>(dataset.variables).map(normalizeVariable) })), assumptions: arrayValue<string>(plan.assumptions), unresolved_mappings: arrayValue<string>(plan.unresolved_mappings) } };
}
function domainIssues(envelope: DomainReviewEnvelope): string[] {
  const issues: string[] = [];
  const sources = envelope.source_spec.datasets.map((item) => item.name);
  const mapped = new Set(envelope.domain_mapping.domain_mappings.map((item) => item.source_dataset));
  const notMapped = new Set(envelope.domain_mapping.unmapped_datasets.map((item) => item.source_dataset));
  const mappingsByTarget = new Map<string, DomainMapping[]>();
  const targetsBySource = new Map<string, Set<string>>();
  sources.forEach((source) => {
    if (!mapped.has(source) && !notMapped.has(source)) issues.push(`${source} needs a mapped or not-mapped disposition before approval.`);
    if (mapped.has(source) && notMapped.has(source)) issues.push(`${source} cannot be both mapped and marked not mapped.`);
  });
  envelope.domain_mapping.domain_mappings.forEach((item) => {
    if (!sources.includes(item.source_dataset)) issues.push(`${item.source_dataset} is not in the approved source inventory.`);
    if (!item.target_domain.trim()) issues.push(`${item.source_dataset} needs a target domain.`);
    if (!item.rationale.trim()) issues.push(`${item.source_dataset} → ${item.target_domain} needs a rationale.`);
    mappingsByTarget.set(item.target_domain, [...(mappingsByTarget.get(item.target_domain) ?? []), item]);
    const targets = targetsBySource.get(item.source_dataset) ?? new Set<string>();
    targets.add(item.target_domain);
    targetsBySource.set(item.source_dataset, targets);
  });
  envelope.domain_mapping.domain_mappings.forEach((item) => {
    if (item.relationship === "split" && (targetsBySource.get(item.source_dataset)?.size ?? 0) < 2) issues.push(`${item.source_dataset} is marked split but feeds only one target domain.`);
  });
  mappingsByTarget.forEach((mappings, domain) => {
    const stackSources = mappings.filter((item) => item.relationship === "stack");
    const directSources = mappings.filter((item) => item.relationship === "direct");
    if (stackSources.length === 1) issues.push(`${domain} has only one stack source; mark every appended source as stack.`);
    if (directSources.length > 1) issues.push(`${domain} has multiple direct sources; classify row appends as stack or keyed column additions as join.`);
  });
  envelope.domain_mapping.unmapped_datasets.forEach((item) => {
    if (!sources.includes(item.source_dataset)) issues.push(`${item.source_dataset} is not in the approved source inventory.`);
    if (!item.rationale.trim()) issues.push(`${item.source_dataset} needs a rationale for not being mapped.`);
  });
  return Array.from(new Set(issues));
}

function variableIssues(envelope: VariableReviewEnvelope): string[] {
  const issues: string[] = [];
  const approved = new Map<string, Set<string>>();
  envelope.domain_mapping.domain_mappings.forEach((item) => {
    const sources = approved.get(item.target_domain) ?? new Set<string>();
    sources.add(item.source_dataset);
    approved.set(item.target_domain, sources);
  });
  const datasets = new Map(envelope.variable_mapping.datasets.map((item) => [item.domain, item]));
  approved.forEach((sources, domain) => {
    const dataset = datasets.get(domain);
    if (!dataset) { issues.push(`${domain} needs a variable matrix.`); return; }
    if (!dataset.variables.length) issues.push(`${domain} needs at least one variable.`);
    dataset.variables.forEach((variable) => {
      const label = `${domain}.${variable.name || "[unnamed]"}`;
      if (!variable.name.trim()) issues.push(`${domain} has a variable without a target name.`);
      variable.sources.forEach((source) => { if (!source.dataset.trim() || !source.variable.trim()) issues.push(`${label} has an incomplete source reference.`); else if (!sources.has(source.dataset)) issues.push(`${label} uses source ${source.dataset}, which is not approved for ${domain}.`); });
      if (variable.mapping_type === "direct" && variable.sources.length !== 1) issues.push(`${label} direct mapping needs exactly one source reference.`);
      if (variable.mapping_type === "assigned" && variable.sources.length) issues.push(`${label} assigned mapping cannot have source references.`);
      if (!variable.sources.length && !allowsSourcelessOrigin(variable.origin)) issues.push(`${label} needs an assigned or derived origin when no raw source is used.`);
      if (!variable.sources.length && (!variable.mapping_expression.trim() || variable.mapping_expression.trim().toLowerCase() === "direct")) issues.push(`${label} needs explicit assignment or derivation logic.`);
      variable.value_level_metadata.forEach((vlm, index) => vlm.sources.forEach((source) => { if (!source.dataset.trim() || !source.variable.trim()) issues.push(`${label} VLM ${index + 1} has an incomplete source reference.`); else if (!sources.has(source.dataset)) issues.push(`${label} VLM ${index + 1} uses an unapproved source.`); }));
    });
    issues.push(...vlmMatrixIssues(domain, dataset.variables));
  });
  datasets.forEach((_dataset, domain) => { if (!approved.has(domain)) issues.push(`${domain} was not approved at the domain gate.`); });
  return Array.from(new Set(issues));
}
function updateDataset(_plan: SDTMVariableMappingPlanDraft, domain: string, update: (mutate: (next: SDTMVariableMappingPlanDraft) => void) => void, key: keyof SDTMDataset, value: unknown) { update((next) => { const dataset = next.datasets.find((item) => item.domain === domain); if (dataset) (dataset as unknown as Record<string, unknown>)[key] = value; }); }
function domainReviewNotes(plan: SDTMVariableMappingPlanDraft, mapping: SDTMDomainMappingPlanDraft, domain: string, key: "review_assumptions" | "review_unresolved_mappings"): string[] { const dataset = plan.datasets.find((item) => item.domain === domain); if (!dataset) return []; if (plan.datasets.some((item) => item.review_assumptions.length || item.review_unresolved_mappings.length)) return dataset[key]; const planKey = key === "review_assumptions" ? "assumptions" : "unresolved_mappings"; return plan[planKey].filter((note) => legacyNoteDomain(note, plan, mapping) === domain); }
function stageWideReviewNotes(plan: SDTMVariableMappingPlanDraft, mapping: SDTMDomainMappingPlanDraft, key: "assumptions" | "unresolved_mappings"): string[] { const datasetKey = key === "assumptions" ? "review_assumptions" : "review_unresolved_mappings"; if (plan.datasets.some((item) => item.review_assumptions.length || item.review_unresolved_mappings.length)) { const owned = new Set(plan.datasets.flatMap((item) => item[datasetKey])); return plan[key].filter((item) => !owned.has(item)); } return plan[key].filter((note) => legacyNoteDomain(note, plan, mapping) === null); }

function RelationshipGuide() {
  return <div className="grid gap-2 rounded-xl border border-white/10 bg-white/[0.02] p-3 text-[11px] leading-5 text-zinc-500 sm:grid-cols-2 xl:grid-cols-5"><span><strong className="text-emerald-300">Direct</strong> keeps one source&apos;s row structure.</span><span><strong className="text-violet-300">Stack</strong> appends observations as new rows.</span><span><strong className="text-sky-300">Join</strong> adds columns by reviewed keys and cardinality.</span><span><strong className="text-amber-300">Split</strong> routes one source to multiple domains.</span><span><strong className="text-zinc-300">Derived</strong> constructs records without a row-aligned source.</span></div>;
}
function hydrateLegacyReviewNotes(plan: SDTMVariableMappingPlanDraft, mapping: SDTMDomainMappingPlanDraft) { if (plan.datasets.some((item) => item.review_assumptions.length || item.review_unresolved_mappings.length)) return; for (const dataset of plan.datasets) { dataset.review_assumptions = plan.assumptions.filter((note) => legacyNoteDomain(note, plan, mapping) === dataset.domain); dataset.review_unresolved_mappings = plan.unresolved_mappings.filter((note) => legacyNoteDomain(note, plan, mapping) === dataset.domain); } }
function legacyNoteDomain(note: string, plan: SDTMVariableMappingPlanDraft, mapping: SDTMDomainMappingPlanDraft): string | null { const upper = note.toUpperCase(); const matches: Array<{ domain: string; index: number; priority: number }> = []; for (const dataset of plan.datasets) { const domain = dataset.domain.toUpperCase(); const variableMatch = upper.search(new RegExp(`\\b${escapeRegExp(domain)}[A-Z0-9_]{2,}\\b`)); if (variableMatch >= 0) matches.push({ domain, index: variableMatch, priority: 0 }); const sources = mapping.domain_mappings.filter((item) => item.target_domain.toUpperCase() === domain).map((item) => item.source_dataset.toUpperCase()); for (const source of sources) { const sourceMatch = upper.indexOf(source); if (sourceMatch >= 0) matches.push({ domain, index: sourceMatch, priority: 1 }); } const explicit = [new RegExp(`\\b(?:TARGET|DOMAIN)\\s+${escapeRegExp(domain)}\\b`), new RegExp(`\\b${escapeRegExp(domain)}\\s+DOMAIN\\b`), new RegExp(`->\\s*${escapeRegExp(domain)}\\b`), new RegExp(`\\b${escapeRegExp(domain)}\\.`)]; for (const pattern of explicit) { const found = upper.search(pattern); if (found >= 0) matches.push({ domain, index: found, priority: 2 }); } } matches.sort((left, right) => left.priority - right.priority || left.index - right.index); return matches[0]?.domain ?? null; }
function escapeRegExp(value: string): string { return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); }
function recordValue(value: unknown): Record<string, unknown> { return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {}; }
function stringValue(value: unknown, fallback: string): string { return typeof value === "string" ? value : fallback; }
function arrayValue<T>(value: unknown): T[] { return Array.isArray(value) ? value as T[] : []; }
function encodePatchSelector(value: string): string { return value.replaceAll("~", "~0").replaceAll("/", "~1"); }
function allowsSourcelessOrigin(value: string): boolean { const normalized = value.trim().toLowerCase(); return ["assigned", "derived", "protocol", "system", "sponsor"].some((token) => normalized.includes(token)); }
function splitLines(value: string): string[] { return value.split("\n").map((item) => item.trim()).filter(Boolean); }
