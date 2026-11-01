"use client";

import { ArrowDown, ArrowUp, Pencil, Plus, Trash2, X } from "lucide-react";
import { useState, type ReactNode } from "react";
import type { ReviewPatchOperation } from "@/lib/types";
import { Button } from "./ui/button";

export type SDTMDataType = "Char" | "Num";
export type SDTMMappingType = "direct" | "assigned" | "derived" | "coalesce" | "lookup" | "transpose" | "aggregate";
export type SDTMSourceRole = "value" | "join_key" | "lookup" | "filter" | "timing" | "grouping" | "sequence";
export type SDTMRecordOperation = "read" | "stack" | "join" | "transpose" | "filter" | "deduplicate" | "aggregate";
export type SDTMSourceRelationship = "direct" | "stack" | "join" | "split" | "derived";

export interface SDTMSourceReference {
  dataset: string;
  variable: string;
  role: SDTMSourceRole;
}

export interface SourceInventoryDataset {
  name: string;
  label?: string;
  variables?: Array<{ name: string; label?: string }>;
}

export interface SDTMJoinKey { left: string; right: string; }
export interface SDTMStackColumnSource { input: string; variable: string; }
export interface SDTMStackColumn { target: string; sources: SDTMStackColumnSource[]; }
export interface SDTMTransposeValue { source_variable: string; name_value: string; }
export interface SDTMAggregation { output_variable: string; operation: "count" | "sum" | "min" | "max" | "mean" | "first" | "last"; source_variable: string | null; }

export interface SDTMRecordStep {
  step_id: string;
  operation: SDTMRecordOperation;
  description: string;
  output: string;
  inputs: string[];
  source_dataset: string | null;
  column_alignment: SDTMStackColumn[];
  left: string | null;
  right: string | null;
  join_type: "left" | "inner" | "full" | "right" | null;
  join_keys: SDTMJoinKey[];
  cardinality: "one_to_one" | "one_to_many" | "many_to_one" | "many_to_many" | null;
  id_variables: string[];
  value_variables: string[];
  name_variable: string | null;
  value_variable: string | null;
  transpose_values: SDTMTransposeValue[];
  condition: string | null;
  sas_condition: string | null;
  keys: string[];
  order_by: string[];
  keep: "first" | "last";
  group_by: string[];
  aggregations: SDTMAggregation[];
  review_notes: string[];
}

export interface SDTMRecordPlan { steps: SDTMRecordStep[]; output_step: string; }

export interface SDTMValueLevelMetadataDraft {
  where_clause: string;
  label: string;
  data_type: SDTMDataType;
  origin: string;
  mapping_expression: string;
  sources: SDTMSourceReference[];
  controlled_terms: string[];
}

export interface SDTMVariableDraft {
  name: string;
  label: string;
  data_type: SDTMDataType;
  mapping_type: SDTMMappingType;
  sources: SDTMSourceReference[];
  origin: string;
  mapping_expression: string;
  controlled_terms: string[];
  value_level_metadata: SDTMValueLevelMetadataDraft[];
  crf_source_label: string | null;
  length?: number | null;
  format?: string | null;
  role?: string | null;
  core?: "Req" | "Exp" | "Perm" | null;
  comment?: string | null;
}

const inputClass = "focus-ring min-h-9 w-full rounded-md border border-white/10 bg-[#101012] px-2.5 py-2 text-xs text-zinc-200 placeholder:text-zinc-600";
const roles: SDTMSourceRole[] = ["value", "join_key", "lookup", "filter", "timing", "grouping", "sequence"];
const operations: SDTMRecordOperation[] = ["read", "stack", "join", "transpose", "filter", "deduplicate", "aggregate"];

export function SourceReferencesEditor({ value, onChange, inventory, allowedDatasets, label = "Source lineage" }: {
  value: SDTMSourceReference[];
  onChange: (value: SDTMSourceReference[]) => void;
  inventory: SourceInventoryDataset[];
  allowedDatasets: string[];
  label?: string;
}) {
  const datasets = allowedDatasets.length ? allowedDatasets : inventory.map((item) => item.name);
  const update = (index: number, next: Partial<SDTMSourceReference>) => onChange(value.map((item, itemIndex) => itemIndex === index ? { ...item, ...next } : item));
  const add = () => {
    const dataset = datasets[0] ?? "";
    const variable = inventory.find((item) => item.name === dataset)?.variables?.[0]?.name ?? "";
    onChange([...value, { dataset, variable, role: "value" }]);
  };
  return <div className="space-y-2">
    <div className="flex items-center justify-between gap-2"><EditorLabel>{label}</EditorLabel><button type="button" aria-label={`Add ${label}`} onClick={add} className="flex items-center gap-1 rounded-md border border-dashed border-violet-500/30 px-2 py-1 text-[10px] font-black uppercase tracking-wider text-violet-300"><Plus size={11} />Source</button></div>
    {value.map((reference, index) => {
      const sourceVariables = inventory.find((item) => item.name === reference.dataset)?.variables ?? [];
      const listId = `source-fields-${reference.dataset}-${index}`.replace(/[^A-Za-z0-9_-]/g, "-");
      return <div key={`${reference.dataset}-${reference.variable}-${index}`} className="grid gap-2 rounded-lg border border-violet-500/15 bg-violet-500/[0.04] p-2 md:grid-cols-[minmax(130px,0.9fr)_minmax(130px,1fr)_120px_36px]">
        <select aria-label={`${label} ${index + 1} dataset`} value={reference.dataset} onChange={(event) => update(index, { dataset: event.target.value, variable: "" })} className={inputClass}><option value="">Choose dataset</option>{datasets.map((dataset) => <option key={dataset}>{dataset}</option>)}</select>
        <div><input aria-label={`${label} ${index + 1} variable`} list={listId} value={reference.variable} onChange={(event) => update(index, { variable: event.target.value.toUpperCase() })} placeholder="Source variable" className={`${inputClass} font-mono`} /><datalist id={listId}>{sourceVariables.map((variable) => <option key={variable.name} value={variable.name}>{variable.label}</option>)}</datalist></div>
        <select aria-label={`${label} ${index + 1} role`} value={reference.role} onChange={(event) => update(index, { role: event.target.value as SDTMSourceRole })} className={inputClass}>{roles.map((role) => <option key={role} value={role}>{role.replace("_", " ")}</option>)}</select>
        <button type="button" aria-label={`Remove ${label} ${index + 1}`} onClick={() => onChange(value.filter((_, itemIndex) => itemIndex !== index))} className="grid h-9 w-9 place-items-center rounded-md text-zinc-600 hover:bg-rose-500/10 hover:text-rose-300"><Trash2 size={13} /></button>
      </div>;
    })}
    {!value.length && <p className="rounded-lg border border-dashed border-white/10 px-3 py-2 text-[11px] text-zinc-600">No raw source references. Use this only for reviewed assigned or derived values.</p>}
  </div>;
}

export function RecordPlanEditor({ value, onChange, allowedDatasets }: {
  value: SDTMRecordPlan;
  onChange: (value: SDTMRecordPlan) => void;
  allowedDatasets: string[];
}) {
  const [newOperation, setNewOperation] = useState<SDTMRecordOperation>("read");
  const updateStep = (index: number, next: Partial<SDTMRecordStep>) => onChange({ ...value, steps: value.steps.map((item, itemIndex) => itemIndex === index ? { ...item, ...next } : item) });
  const addStep = () => {
    const index = value.steps.length + 1;
    const step = newRecordStep(newOperation, index, allowedDatasets, value.steps);
    onChange({ steps: [...value.steps, step], output_step: step.step_id });
  };
  const removeStep = (index: number) => {
    const removed = value.steps[index];
    const steps = value.steps.filter((_, itemIndex) => itemIndex !== index);
    onChange({ steps, output_step: value.output_step === removed.step_id ? steps.at(-1)?.step_id ?? "" : value.output_step });
  };
  const move = (index: number, offset: number) => {
    const target = index + offset;
    if (target < 0 || target >= value.steps.length) return;
    const steps = [...value.steps];
    [steps[index], steps[target]] = [steps[target], steps[index]];
    onChange({ ...value, steps });
  };
  return <section className="space-y-3 rounded-xl border border-cyan-500/15 bg-cyan-500/[0.025] p-4">
    <div className="flex flex-wrap items-end justify-between gap-3"><div><p className="text-xs font-black uppercase tracking-[0.12em] text-cyan-200">Record construction pipeline</p><p className="mt-1 text-xs leading-5 text-zinc-500">Ordered, human-approved steps compile deterministically into each domain&apos;s R and SAS program.</p></div><label className="min-w-48"><EditorLabel>Final output step</EditorLabel><select aria-label="Final output step" value={value.output_step} onChange={(event) => onChange({ ...value, output_step: event.target.value })} className={inputClass}><option value="">Choose final step</option>{value.steps.map((step) => <option key={step.step_id} value={step.step_id}>{step.step_id}</option>)}</select></label></div>
    {value.steps.map((step, index) => {
      const priorSteps = value.steps.slice(0, index);
      return <article key={`${step.step_id}-${index}`} className="rounded-xl border border-white/10 bg-[#121214] p-3">
        <div className="grid gap-2 lg:grid-cols-[44px_minmax(120px,0.65fr)_140px_minmax(150px,0.7fr)_minmax(220px,1.5fr)_36px]">
          <div className="flex gap-1"><button type="button" aria-label={`Move ${step.step_id} up`} disabled={index === 0} onClick={() => move(index, -1)} className="text-zinc-500 disabled:opacity-20"><ArrowUp size={14} /></button><button type="button" aria-label={`Move ${step.step_id} down`} disabled={index === value.steps.length - 1} onClick={() => move(index, 1)} className="text-zinc-500 disabled:opacity-20"><ArrowDown size={14} /></button></div>
          <label><EditorLabel>Step ID</EditorLabel><input aria-label={`Step ${index + 1} ID`} value={step.step_id} onChange={(event) => { const stepId = event.target.value; onChange({ steps: value.steps.map((item, itemIndex) => itemIndex === index ? { ...item, step_id: stepId } : item), output_step: value.output_step === step.step_id ? stepId : value.output_step }); }} className={`${inputClass} font-mono`} /></label>
          <label><EditorLabel>Operation</EditorLabel><select aria-label={`Step ${index + 1} operation`} value={step.operation} onChange={(event) => updateStep(index, { ...operationDefaults(event.target.value as SDTMRecordOperation), operation: event.target.value as SDTMRecordOperation })} className={inputClass}>{operations.map((operation) => <option key={operation}>{operation}</option>)}</select></label>
          <label><EditorLabel>Output name</EditorLabel><input value={step.output} onChange={(event) => updateStep(index, { output: event.target.value })} className={`${inputClass} font-mono`} /></label>
          <label><EditorLabel>Description</EditorLabel><input value={step.description} onChange={(event) => updateStep(index, { description: event.target.value })} className={inputClass} /></label>
          <button type="button" aria-label={`Remove step ${step.step_id}`} onClick={() => removeStep(index)} className="mt-5 grid h-9 w-9 place-items-center rounded-md text-zinc-600 hover:bg-rose-500/10 hover:text-rose-300"><Trash2 size={14} /></button>
        </div>
        <div className="mt-3 border-t border-white/[0.07] pt-3"><RecordOperationFields step={step} priorSteps={priorSteps} allowedDatasets={allowedDatasets} onChange={(next) => updateStep(index, next)} /></div>
      </article>;
    })}
    {!value.steps.length && <p className="rounded-lg border border-dashed border-amber-500/20 p-4 text-center text-xs text-amber-200">Add at least one read step.</p>}
    <div className="flex justify-end gap-2"><select aria-label="New record operation" value={newOperation} onChange={(event) => setNewOperation(event.target.value as SDTMRecordOperation)} className={`${inputClass} max-w-40`}>{operations.map((operation) => <option key={operation}>{operation}</option>)}</select><Button type="button" variant="outline" size="sm" onClick={addStep}><Plus size={13} />Operation</Button></div>
  </section>;
}

function RecordOperationFields({ step, priorSteps, allowedDatasets, onChange }: { step: SDTMRecordStep; priorSteps: SDTMRecordStep[]; allowedDatasets: string[]; onChange: (value: Partial<SDTMRecordStep>) => void }) {
  const priorOptions = priorSteps.map((item) => item.step_id);
  if (step.operation === "read") return <label><EditorLabel>Approved source dataset</EditorLabel><select aria-label={`${step.step_id} source dataset`} value={step.source_dataset ?? ""} onChange={(event) => onChange({ source_dataset: event.target.value || null })} className={`${inputClass} max-w-sm`}><option value="">Choose source</option>{allowedDatasets.map((source) => <option key={source}>{source}</option>)}</select></label>;
  if (step.operation === "stack") return <div className="space-y-3"><StepInputs value={step.inputs} options={priorOptions} onChange={(inputs) => onChange({ inputs })} label="Steps to stack" /><div><div className="flex items-center justify-between"><EditorLabel>Column alignment</EditorLabel><button type="button" onClick={() => onChange({ column_alignment: [...step.column_alignment, { target: "", sources: step.inputs.map((input) => ({ input, variable: "" })) }] })} className="text-[10px] font-bold text-violet-300">+ aligned column</button></div>{step.column_alignment.map((column, index) => <div key={index} className="mt-2 grid gap-2 rounded-lg border border-white/[0.07] p-2 md:grid-cols-[140px_1fr_36px]"><input aria-label={`Stack target column ${index + 1}`} value={column.target} onChange={(event) => onChange({ column_alignment: replaceAt(step.column_alignment, index, { ...column, target: event.target.value.toUpperCase() }) })} placeholder="Target column" className={inputClass} /><div className="grid gap-2 sm:grid-cols-2">{step.inputs.map((input) => { const source = column.sources.find((item) => item.input === input); return <label key={input}><span className="mb-1 block font-mono text-[9px] text-zinc-600">{input}</span><input value={source?.variable ?? ""} onChange={(event) => { const sources = column.sources.filter((item) => item.input !== input); if (event.target.value) sources.push({ input, variable: event.target.value.toUpperCase() }); onChange({ column_alignment: replaceAt(step.column_alignment, index, { ...column, sources }) }); }} placeholder="Source variable" className={inputClass} /></label>; })}</div><RemoveButton label={`Remove stack column ${index + 1}`} onClick={() => onChange({ column_alignment: step.column_alignment.filter((_, itemIndex) => itemIndex !== index) })} /></div>)}</div></div>;
  if (step.operation === "join") return <div className="space-y-3"><div className="grid gap-2 md:grid-cols-4"><StepSelect label="Left step" value={step.left} options={priorOptions} onChange={(left) => onChange({ left })} /><StepSelect label="Right step" value={step.right} options={priorOptions} onChange={(right) => onChange({ right })} /><label><EditorLabel>Join type</EditorLabel><select value={step.join_type ?? ""} onChange={(event) => onChange({ join_type: event.target.value as SDTMRecordStep["join_type"] })} className={inputClass}>{["left", "inner", "full", "right"].map((item) => <option key={item}>{item}</option>)}</select></label><label><EditorLabel>Cardinality</EditorLabel><select value={step.cardinality ?? ""} onChange={(event) => onChange({ cardinality: event.target.value as SDTMRecordStep["cardinality"] })} className={inputClass}>{["one_to_one", "one_to_many", "many_to_one", "many_to_many"].map((item) => <option key={item}>{item}</option>)}</select></label></div><PairList label="Join keys" leftLabel="Left variable" rightLabel="Right variable" values={step.join_keys} onChange={(join_keys) => onChange({ join_keys })} /></div>;
  if (step.operation === "transpose") return <div className="grid gap-3 md:grid-cols-2"><StepSelect label="Input step" value={step.inputs[0] ?? null} options={priorOptions} onChange={(input) => onChange({ inputs: input ? [input] : [] })} /><ListInput label="ID variables" value={step.id_variables} onChange={(id_variables) => onChange({ id_variables })} /><ListInput label="Value variables" value={step.value_variables} onChange={(value_variables) => onChange({ value_variables })} /><label><EditorLabel>Name variable</EditorLabel><input value={step.name_variable ?? ""} onChange={(event) => onChange({ name_variable: event.target.value.toUpperCase() || null })} className={inputClass} /></label><label><EditorLabel>Value variable</EditorLabel><input value={step.value_variable ?? ""} onChange={(event) => onChange({ value_variable: event.target.value.toUpperCase() || null })} className={inputClass} /></label><div className="md:col-span-2"><PairList label="Value-level name mapping" leftLabel="Source variable" rightLabel="Name value" values={step.transpose_values.map((item) => ({ left: item.source_variable, right: item.name_value }))} onChange={(items) => onChange({ transpose_values: items.map((item) => ({ source_variable: item.left, name_value: item.right })) })} /></div></div>;
  if (step.operation === "filter") return <div className="grid gap-3 md:grid-cols-2"><StepSelect label="Input step" value={step.inputs[0] ?? null} options={priorOptions} onChange={(input) => onChange({ inputs: input ? [input] : [] })} /><span /><label><EditorLabel>Reviewed R condition</EditorLabel><textarea value={step.condition ?? ""} onChange={(event) => onChange({ condition: event.target.value || null })} className={inputClass} /></label><label><EditorLabel>Reviewed SAS condition</EditorLabel><textarea value={step.sas_condition ?? ""} onChange={(event) => onChange({ sas_condition: event.target.value || null })} className={inputClass} /></label></div>;
  if (step.operation === "deduplicate") return <div className="grid gap-3 md:grid-cols-4"><StepSelect label="Input step" value={step.inputs[0] ?? null} options={priorOptions} onChange={(input) => onChange({ inputs: input ? [input] : [] })} /><ListInput label="Keys" value={step.keys} onChange={(keys) => onChange({ keys })} /><ListInput label="Order by" value={step.order_by} onChange={(order_by) => onChange({ order_by })} /><label><EditorLabel>Keep</EditorLabel><select value={step.keep} onChange={(event) => onChange({ keep: event.target.value as "first" | "last" })} className={inputClass}><option>first</option><option>last</option></select></label></div>;
  return <div className="space-y-3"><div className="grid gap-3 md:grid-cols-2"><StepSelect label="Input step" value={step.inputs[0] ?? null} options={priorOptions} onChange={(input) => onChange({ inputs: input ? [input] : [] })} /><ListInput label="Group by" value={step.group_by} onChange={(group_by) => onChange({ group_by })} /></div><div className="flex items-center justify-between"><EditorLabel>Aggregations</EditorLabel><button type="button" onClick={() => onChange({ aggregations: [...step.aggregations, { output_variable: "", operation: "count", source_variable: null }] })} className="text-[10px] font-bold text-violet-300">+ aggregation</button></div>{step.aggregations.map((item, index) => <div key={index} className="grid gap-2 md:grid-cols-[1fr_140px_1fr_36px]"><input value={item.output_variable} onChange={(event) => onChange({ aggregations: replaceAt(step.aggregations, index, { ...item, output_variable: event.target.value.toUpperCase() }) })} placeholder="Output variable" className={inputClass} /><select value={item.operation} onChange={(event) => onChange({ aggregations: replaceAt(step.aggregations, index, { ...item, operation: event.target.value as SDTMAggregation["operation"] }) })} className={inputClass}>{["count", "sum", "min", "max", "mean", "first", "last"].map((operation) => <option key={operation}>{operation}</option>)}</select><input disabled={item.operation === "count"} value={item.source_variable ?? ""} onChange={(event) => onChange({ aggregations: replaceAt(step.aggregations, index, { ...item, source_variable: event.target.value.toUpperCase() || null }) })} placeholder="Source variable" className={inputClass} /><RemoveButton label={`Remove aggregation ${index + 1}`} onClick={() => onChange({ aggregations: step.aggregations.filter((_, itemIndex) => itemIndex !== index) })} /></div>)}</div>;
}

export function VariableMappingMatrix({ variables, onChange, inventory, allowedDatasets, sourceRelationships, domain, proposalOperations = [] }: {
  variables: SDTMVariableDraft[];
  onChange: (variables: SDTMVariableDraft[]) => void;
  inventory: SourceInventoryDataset[];
  allowedDatasets: string[];
  sourceRelationships: Array<{ dataset: string; relationship: SDTMSourceRelationship }>;
  domain?: string;
  proposalOperations?: ReviewPatchOperation[];
}) {
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const [addingVlmColumn, setAddingVlmColumn] = useState(false);
  const [vlmDataset, setVlmDataset] = useState(allowedDatasets[0] ?? "");
  const [vlmWhereClause, setVlmWhereClause] = useState("");
  const [vlmTargetIndexes, setVlmTargetIndexes] = useState<number[]>([]);
  const selected = selectedIndex === null ? null : variables[selectedIndex] ?? null;
  const proposedVariables = proposalOperations.length && domain
    ? projectVariableMappingProposal(domain, variables, proposalOperations)
    : variables;
  const sourceColumns = buildVariableMatrixColumns([...variables, ...proposedVariables], allowedDatasets, sourceRelationships);
  const currentColumnKeys = new Set(buildVariableMatrixColumns(variables, allowedDatasets, sourceRelationships).map((column) => column.key));
  const updateSelected = (next: SDTMVariableDraft[]) => {
    if (selectedIndex === null || !next[0]) return;
    onChange(replaceAt(variables, selectedIndex, next[0]));
  };
  const openVlmColumnDialog = () => {
    const defaults = variables.flatMap((variable, index) => variable.mapping_type === "transpose" || variable.value_level_metadata.length ? [index] : []);
    setVlmDataset(allowedDatasets[0] ?? sourceRelationships[0]?.dataset ?? "");
    setVlmWhereClause("");
    setVlmTargetIndexes(defaults.length ? defaults : variables.length ? [0] : []);
    setAddingVlmColumn(true);
  };
  const addVlmColumn = () => {
    const whereClause = vlmWhereClause.trim();
    if (!whereClause || !vlmDataset || !vlmTargetIndexes.length) return;
    onChange(variables.map((variable, index) => {
      if (!vlmTargetIndexes.includes(index)) return variable;
      const existingIndex = variable.value_level_metadata.findIndex((item) => canonicalWhereClause(item.where_clause) === canonicalWhereClause(whereClause));
      if (existingIndex < 0) return { ...variable, value_level_metadata: [...variable.value_level_metadata, newVlm(whereClause, vlmDataset)] };
      const existing = variable.value_level_metadata[existingIndex];
      if (existing.sources.some((source) => source.dataset === vlmDataset)) return variable;
      return { ...variable, value_level_metadata: replaceAt(variable.value_level_metadata, existingIndex, { ...existing, sources: [...existing.sources, { dataset: vlmDataset, variable: "", role: "value" }] }) };
    }));
    setAddingVlmColumn(false);
  };
  const removeVlmColumn = (column: VariableMatrixColumn) => onChange(variables.map((variable) => ({
    ...variable,
    value_level_metadata: variable.value_level_metadata.flatMap((item) => {
      if (canonicalWhereClause(item.where_clause) !== canonicalWhereClause(column.whereClause ?? "")) return [item];
      const sources = item.sources.filter((source) => source.dataset !== column.dataset);
      return sources.length ? [{ ...item, sources }] : [];
    }),
  })));
  return <>
    <section className="overflow-hidden rounded-xl border border-white/10 bg-[#121214]">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-white/[0.07] px-4 py-3">
        <div><p className="text-xs font-black uppercase tracking-[0.12em] text-violet-200">Variable &amp; VLM mapping matrix</p>
        <p className="mt-1 max-w-4xl text-xs leading-5 text-zinc-500">Rows are SDTM variables. Direct and stack sources remain separate columns; joined lookup sources are labeled separately because they add columns rather than append records. Each value-level condition is a shared column, so related test code, result, and unit mappings can be reviewed in the correct cells.</p>
        {proposalOperations.length > 0 && <div className="mt-2 flex flex-wrap items-center gap-2 text-[10px]"><span className="rounded-full border border-amber-400/25 bg-amber-400/10 px-2 py-1 font-black uppercase tracking-wider text-amber-200">Proposed overlay · {proposalOperations.length} changes</span><span className="text-zinc-500">Changed cells show current and proposed content together. Unmarked cells remain unchanged.</span></div>}</div>
        <Button type="button" variant="outline" size="sm" onClick={openVlmColumnDialog}><Plus size={13} />Add VLM column</Button>
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-full border-collapse text-left text-xs">
          <thead className="bg-black/20 text-zinc-400">
            <tr>
              <th className="sticky left-0 z-10 min-w-56 border-b border-r border-white/[0.07] bg-[#101012] px-3 py-3">SDTM variable</th>
              {sourceColumns.map((column) => <th key={column.key} className="min-w-48 border-b border-r border-white/[0.07] px-3 py-3 align-top last:border-r-0">
                <div className="flex items-start justify-between gap-2"><div><div className="flex items-center gap-2"><span className="font-mono font-bold text-zinc-200">{column.dataset}</span><RelationshipBadge relationship={column.relationship} /></div>
                {column.whereClause && <span className="mt-1 block max-w-64 whitespace-normal font-mono text-[10px] font-normal leading-4 text-cyan-300">{column.whereClause}</span>}{!currentColumnKeys.has(column.key) && <span className="mt-1 inline-block rounded-full border border-emerald-400/20 bg-emerald-400/10 px-1.5 py-0.5 text-[8px] font-black uppercase tracking-wider text-emerald-300">Proposed column</span>}</div>
                {column.whereClause && currentColumnKeys.has(column.key) && <button type="button" aria-label={`Remove VLM column ${column.dataset} ${column.whereClause}`} onClick={() => removeVlmColumn(column)} className="grid h-7 w-7 shrink-0 place-items-center rounded-md text-zinc-600 hover:bg-rose-500/10 hover:text-rose-300"><Trash2 size={12} /></button>}</div>
              </th>)}
              {!sourceColumns.length && <th className="min-w-48 border-b border-white/[0.07] px-3 py-3 text-zinc-600">Assigned / derived</th>}
            </tr>
          </thead>
          <tbody>
            {variables.map((variable, index) => {
              const proposed = proposedVariables[index] ?? variable;
              const metadataChanged = variableMetadataSignature(variable) !== variableMetadataSignature(proposed);
              return <tr key={`${variable.name}-${index}`} className="group border-b border-white/[0.05] last:border-b-0">
              <th className="sticky left-0 z-[5] border-r border-white/[0.07] bg-[#121214] p-0 group-hover:bg-[#17171a]">
                <button type="button" aria-label={`Edit ${variable.name || `variable ${index + 1}`} mapping`} onClick={() => setSelectedIndex(index)} className="flex w-full items-start justify-between gap-3 px-3 py-3 text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-violet-400">
                  <span><span className="block font-mono text-sm font-black text-violet-200">{variable.name || "[unnamed]"}</span><span className="mt-1 block font-normal text-zinc-500">{variable.label || "No label"} · {variable.data_type} · {variable.mapping_type}</span>{metadataChanged && <span className="mt-2 block rounded-md border border-amber-400/20 bg-amber-400/[0.07] p-2 text-[10px] font-normal leading-4"><span className="font-black uppercase tracking-wider text-amber-200">Proposed metadata</span><span className="mt-1 block text-emerald-200">{proposed.label || "No label"} · {proposed.data_type} · {proposed.mapping_type}</span>{variable.mapping_expression !== proposed.mapping_expression && <span className="mt-1 block whitespace-normal text-zinc-400">Logic: {proposed.mapping_expression || "Not present"}</span>}</span>}</span><Pencil size={13} className="mt-1 shrink-0 text-zinc-600 group-hover:text-violet-300" />
                </button>
              </th>
              {sourceColumns.map((column) => <td key={column.key} className="border-r border-white/[0.05] p-0 align-top last:border-r-0">
                <button type="button" aria-label={`Edit ${variable.name || `variable ${index + 1}`} for ${column.dataset}${column.whereClause ? ` ${column.whereClause}` : ""}`} onClick={() => setSelectedIndex(index)} className="min-h-16 w-full px-3 py-3 text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-violet-400">
                  <MatrixCell variable={variable} proposedVariable={proposed} column={column} />
                </button>
              </td>)}
              {!sourceColumns.length && <td className="px-3 py-3 text-zinc-500">{variable.mapping_type}</td>}
            </tr>;})}
          </tbody>
        </table>
      </div>
      {!variables.length && <p className="p-6 text-center text-xs text-zinc-600">No SDTM variables are available for review.</p>}
    </section>
    {addingVlmColumn && <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/75 p-4 pt-[8vh] backdrop-blur-sm" role="dialog" aria-modal="true" aria-labelledby="vlm-column-dialog-title" onMouseDown={(event) => { if (event.currentTarget === event.target) setAddingVlmColumn(false); }}>
      <div className="w-full max-w-2xl rounded-2xl border border-cyan-500/25 bg-[#0d0d0f] shadow-2xl shadow-black/60">
        <div className="flex items-start justify-between gap-4 border-b border-white/10 px-5 py-4"><div><p id="vlm-column-dialog-title" className="text-sm font-black text-cyan-200">Add shared VLM column</p><p className="mt-1 text-xs leading-5 text-zinc-500">Create the same value-level condition for the selected SDTM variables, then edit each matrix cell to assign its correct source variable and mapping.</p></div><button type="button" aria-label="Close VLM column dialog" onClick={() => setAddingVlmColumn(false)} className="grid h-9 w-9 place-items-center rounded-md text-zinc-500 hover:bg-white/5 hover:text-white"><X size={16} /></button></div>
        <div className="space-y-4 p-5"><div className="grid gap-3 md:grid-cols-2"><label><EditorLabel>Source dataset</EditorLabel><select aria-label="VLM source dataset" value={vlmDataset} onChange={(event) => setVlmDataset(event.target.value)} className={inputClass}><option value="">Choose dataset</option>{allowedDatasets.map((dataset) => <option key={dataset}>{dataset}</option>)}</select></label><label><EditorLabel>Where clause</EditorLabel><input aria-label="VLM where clause" value={vlmWhereClause} onChange={(event) => setVlmWhereClause(event.target.value)} placeholder="LBTESTCD = 'GLUC'" className={`${inputClass} font-mono`} /></label></div>
          <div><EditorLabel>Target variable cells</EditorLabel><div className="grid gap-2 sm:grid-cols-2 md:grid-cols-3">{variables.map((variable, index) => <label key={`${variable.name}-${index}`} className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-xs ${vlmTargetIndexes.includes(index) ? "border-cyan-500/30 bg-cyan-500/[0.07] text-cyan-100" : "border-white/10 text-zinc-500"}`}><input type="checkbox" aria-label={`Include ${variable.name} in VLM column`} checked={vlmTargetIndexes.includes(index)} onChange={(event) => setVlmTargetIndexes((current) => event.target.checked ? [...current, index] : current.filter((item) => item !== index))} /><span className="font-mono font-bold">{variable.name || `[variable ${index + 1}]`}</span></label>)}</div></div>
          <div className="flex justify-end gap-2"><Button type="button" variant="outline" onClick={() => setAddingVlmColumn(false)}>Cancel</Button><Button type="button" variant="clinical" disabled={!vlmDataset || !vlmWhereClause.trim() || !vlmTargetIndexes.length} onClick={addVlmColumn}>Create VLM column</Button></div>
        </div>
      </div>
    </div>}
    {selected && <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/75 p-4 pt-[5vh] backdrop-blur-sm" role="dialog" aria-modal="true" aria-labelledby="variable-mapping-dialog-title" onMouseDown={(event) => { if (event.currentTarget === event.target) setSelectedIndex(null); }}>
      <div className="w-full max-w-6xl rounded-2xl border border-violet-500/25 bg-[#0d0d0f] shadow-2xl shadow-black/60">
        <div className="sticky top-0 z-10 flex items-start justify-between gap-4 rounded-t-2xl border-b border-white/10 bg-[#0d0d0f]/95 px-5 py-4 backdrop-blur">
          <div><p id="variable-mapping-dialog-title" className="font-mono text-base font-black text-violet-200">Edit {selected.name || "SDTM variable"}</p><p className="mt-1 text-xs text-zinc-500">Edit target name, label, data type, derivation, source lineage, and value-level metadata.</p></div>
          <button type="button" aria-label="Close variable mapping dialog" onClick={() => setSelectedIndex(null)} className="grid h-9 w-9 place-items-center rounded-md text-zinc-500 hover:bg-white/5 hover:text-white"><X size={16} /></button>
        </div>
        <div className="p-5"><VariableMappingCards variables={[selected]} onChange={updateSelected} inventory={inventory} allowedDatasets={allowedDatasets} removable={false} /></div>
      </div>
    </div>}
  </>;
}

interface VariableMatrixColumn {
  key: string;
  dataset: string;
  relationship: SDTMSourceRelationship;
  whereClause: string | null;
}

function buildVariableMatrixColumns(variables: SDTMVariableDraft[], allowedDatasets: string[], sourceRelationships: Array<{ dataset: string; relationship: SDTMSourceRelationship }>): VariableMatrixColumn[] {
  const relationshipByDataset = new Map(sourceRelationships.map((item) => [item.dataset, item.relationship]));
  const datasets = Array.from(new Set([...allowedDatasets, ...variables.flatMap((variable) => [...variable.sources, ...variable.value_level_metadata.flatMap((vlm) => vlm.sources)].map((source) => source.dataset)).filter(Boolean)]));
  const columns: VariableMatrixColumn[] = datasets.map((dataset) => ({ key: `${dataset}|base`, dataset, relationship: relationshipByDataset.get(dataset) ?? "direct", whereClause: null }));
  const seenSlices = new Set<string>();
  for (const variable of variables) {
    for (const vlm of variable.value_level_metadata) {
      if (!vlm.where_clause.trim()) continue;
      for (const source of vlm.sources) {
        if (!source.dataset) continue;
        const key = `${source.dataset}|${canonicalWhereClause(vlm.where_clause)}`;
        if (seenSlices.has(key)) continue;
        seenSlices.add(key);
        columns.push({ key, dataset: source.dataset, relationship: relationshipByDataset.get(source.dataset) ?? "direct", whereClause: vlm.where_clause.trim() });
      }
    }
  }
  return columns;
}

interface MatrixCellState {
  references: SDTMSourceReference[];
  vlm: SDTMValueLevelMetadataDraft | null;
}

function MatrixCell({ variable, proposedVariable, column }: { variable: SDTMVariableDraft; proposedVariable: SDTMVariableDraft; column: VariableMatrixColumn }) {
  const current = matrixCellState(variable, column);
  const proposed = matrixCellState(proposedVariable, column);
  if (JSON.stringify(current) === JSON.stringify(proposed)) return <MatrixCellValue state={current} />;
  return <span className="block rounded-lg border border-amber-400/25 bg-amber-400/[0.06] p-2">
    <span className="block text-[9px] font-black uppercase tracking-wider text-rose-300">Current</span>
    <span className="mt-1 block opacity-65"><MatrixCellValue state={current} showLogic /></span>
    <span className="mt-2 block border-t border-amber-300/15 pt-2 text-[9px] font-black uppercase tracking-wider text-emerald-300">Proposed</span>
    <span className="mt-1 block"><MatrixCellValue state={proposed} showLogic proposed /></span>
  </span>;
}

function matrixCellState(variable: SDTMVariableDraft, column: VariableMatrixColumn): MatrixCellState {
  if (!column.whereClause) return {
    references: variable.sources.filter((source) => source.dataset === column.dataset),
    vlm: null,
  };
  const matching = variable.value_level_metadata.find((vlm) => canonicalWhereClause(vlm.where_clause) === canonicalWhereClause(column.whereClause ?? ""));
  if (!matching) return { references: [], vlm: null };
  const references = matching.sources.filter((source) => source.dataset === column.dataset);
  const ownsAssignedCell = !matching.sources.length && allowsSourcelessVlmOrigin(matching.origin);
  return { references, vlm: references.length || ownsAssignedCell ? matching : null };
}

function MatrixCellValue({ state, showLogic = false, proposed = false }: { state: MatrixCellState; showLogic?: boolean; proposed?: boolean }) {
  if (!state.references.length && state.vlm && !state.vlm.sources.length) return <span><span className={`block font-bold ${proposed ? "text-emerald-200" : "text-amber-300"}`}>Assigned / derived</span>{showLogic && <span className="mt-1 block whitespace-normal text-[10px] leading-4 text-zinc-500">{state.vlm.mapping_expression}</span>}</span>;
  if (!state.references.length) return <span className="text-zinc-700">{showLogic ? "Empty cell" : "—"}</span>;
  return <span className="space-y-1">{state.references.map((reference, index) => <span key={`${reference.dataset}-${reference.variable}-${reference.role}-${index}`} className="block"><span className={`font-mono font-bold ${proposed ? "text-emerald-200" : "text-zinc-200"}`}>{reference.variable || "[variable]"}</span><span className="ml-2 text-[10px] text-zinc-600">{reference.role.replace("_", " ")}</span></span>)}{showLogic && state.vlm && <span className="mt-1 block whitespace-normal text-[10px] leading-4 text-zinc-500">{state.vlm.mapping_expression}</span>}</span>;
}

function variableMetadataSignature(variable: SDTMVariableDraft): string {
  return JSON.stringify({
    name: variable.name,
    label: variable.label,
    data_type: variable.data_type,
    mapping_type: variable.mapping_type,
    origin: variable.origin,
    mapping_expression: variable.mapping_expression,
    controlled_terms: variable.controlled_terms,
    crf_source_label: variable.crf_source_label,
  });
}

export function projectVariableMappingProposal(domain: string, variables: SDTMVariableDraft[], operations: ReviewPatchOperation[]): SDTMVariableDraft[] {
  const projected = structuredClone(variables);
  for (const operation of operations) {
    const match = operation.path.match(/^\/variable_mapping\/datasets\/domain=([^/]+)\/variables\/name=([^/]+)(?:\/(.*))?$/);
    if (!match || decodePatchSelector(match[1]).toUpperCase() !== domain.toUpperCase()) continue;
    const variableName = decodePatchSelector(match[2]).toUpperCase();
    const variableIndex = projected.findIndex((variable) => variable.name.toUpperCase() === variableName);
    if (variableIndex < 0) continue;
    const tail = match[3] ?? "";
    if (!tail) {
      if (isRecord(operation.after)) projected[variableIndex] = normalizeVariable(operation.after as unknown as SDTMVariableDraft);
      continue;
    }
    applyVariableProposalOperation(projected[variableIndex], tail, operation.after);
  }
  return projected;
}

function applyVariableProposalOperation(variable: SDTMVariableDraft, tail: string, after: unknown): void {
  const segments = tail.split("/").map(decodePatchSelector);
  const [section, selector, field] = segments;
  if (section === "sources" && selector?.startsWith("variable=")) {
    const sourceVariable = selector.slice("variable=".length).toUpperCase();
    const index = variable.sources.findIndex((source) => source.variable.toUpperCase() === sourceVariable);
    if (after === null) {
      if (index >= 0) variable.sources.splice(index, 1);
    } else if (isRecord(after)) {
      const source = normalizeSourceReference(after);
      if (index >= 0) variable.sources[index] = source;
      else variable.sources.push(source);
    }
    return;
  }
  if (section === "value_level_metadata" && selector?.startsWith("where_clause=")) {
    const whereClause = selector.slice("where_clause=".length);
    const index = variable.value_level_metadata.findIndex((item) => canonicalWhereClause(item.where_clause) === canonicalWhereClause(whereClause));
    if (!field) {
      if (after === null) {
        if (index >= 0) variable.value_level_metadata.splice(index, 1);
      } else if (isRecord(after)) {
        const item = normalizeVlm(after);
        if (index >= 0) variable.value_level_metadata[index] = item;
        else variable.value_level_metadata.push(item);
      }
      return;
    }
    if (index < 0) return;
    const item = variable.value_level_metadata[index] as unknown as Record<string, unknown>;
    item[field] = structuredClone(after);
    variable.value_level_metadata[index] = normalizeVlm(item);
    return;
  }
  if (segments.length === 1) {
    const record = variable as unknown as Record<string, unknown>;
    record[section] = structuredClone(after);
    Object.assign(variable, normalizeVariable(variable));
  }
}

function normalizeSourceReference(value: Record<string, unknown>): SDTMSourceReference {
  const role = stringValue(value.role, "value");
  return {
    dataset: stringValue(value.dataset, ""),
    variable: stringValue(value.variable, ""),
    role: roles.includes(role as SDTMSourceRole) ? role as SDTMSourceRole : "value",
  };
}

function normalizeVlm(value: Record<string, unknown>): SDTMValueLevelMetadataDraft {
  return {
    where_clause: stringValue(value.where_clause, ""),
    label: stringValue(value.label, ""),
    data_type: value.data_type === "Num" ? "Num" : "Char",
    origin: stringValue(value.origin, "CRF"),
    mapping_expression: stringValue(value.mapping_expression, ""),
    sources: arrayValue<Record<string, unknown>>(value.sources).map(normalizeSourceReference),
    controlled_terms: arrayValue<string>(value.controlled_terms),
  };
}

function decodePatchSelector(value: string): string { return value.replaceAll("~1", "/").replaceAll("~0", "~"); }

function RelationshipBadge({ relationship }: { relationship: SDTMSourceRelationship }) {
  const styles: Record<SDTMSourceRelationship, string> = { direct: "border-emerald-500/25 bg-emerald-500/10 text-emerald-300", stack: "border-violet-500/25 bg-violet-500/10 text-violet-300", join: "border-sky-500/25 bg-sky-500/10 text-sky-300", split: "border-amber-500/25 bg-amber-500/10 text-amber-300", derived: "border-zinc-500/25 bg-zinc-500/10 text-zinc-400" };
  return <span className={`rounded-full border px-1.5 py-0.5 text-[9px] font-black uppercase tracking-wider ${styles[relationship]}`}>{relationship}</span>;
}

export function VariableMappingCards({ variables, onChange, inventory, allowedDatasets, removable = true }: {
  variables: SDTMVariableDraft[];
  onChange: (variables: SDTMVariableDraft[]) => void;
  inventory: SourceInventoryDataset[];
  allowedDatasets: string[];
  removable?: boolean;
}) {
  const update = (index: number, next: SDTMVariableDraft) => onChange(replaceAt(variables, index, next));
  return <div className="space-y-3">{variables.map((variable, index) => <article key={`${variable.name}-${index}`} className="rounded-xl border border-white/10 bg-[#141416] p-4">
    <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="font-mono text-sm font-black text-violet-200">{variable.name || "[unnamed]"}</p><p className="mt-1 text-xs text-zinc-600">{variable.sources.length} source reference{variable.sources.length === 1 ? "" : "s"} · {variable.mapping_type}</p></div>{removable && <RemoveButton label={`Remove ${variable.name || `variable ${index + 1}`}`} onClick={() => onChange(variables.filter((_, itemIndex) => itemIndex !== index))} />}</div>
    <div className="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-4"><label><EditorLabel>SDTM variable</EditorLabel><input value={variable.name} onChange={(event) => update(index, { ...variable, name: event.target.value.toUpperCase() })} className={`${inputClass} font-mono font-bold`} /></label><label><EditorLabel>Label</EditorLabel><input value={variable.label} onChange={(event) => update(index, { ...variable, label: event.target.value })} className={inputClass} /></label><label><EditorLabel>Data type</EditorLabel><select value={variable.data_type} onChange={(event) => update(index, { ...variable, data_type: event.target.value as SDTMDataType })} className={inputClass}><option>Char</option><option>Num</option></select></label><label><EditorLabel>Mapping type</EditorLabel><select aria-label={`${variable.name} mapping type`} value={variable.mapping_type} onChange={(event) => update(index, { ...variable, mapping_type: event.target.value as SDTMMappingType })} className={inputClass}>{["direct", "assigned", "derived", "coalesce", "lookup", "transpose", "aggregate"].map((item) => <option key={item}>{item}</option>)}</select></label></div>
    <div className="mt-3"><SourceReferencesEditor value={variable.sources} onChange={(sources) => update(index, { ...variable, sources })} inventory={inventory} allowedDatasets={allowedDatasets} label={`${variable.name || `Variable ${index + 1}`} sources`} /></div>
    <div className="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-4"><label className="md:col-span-2"><EditorLabel>Mapping logic</EditorLabel><textarea rows={3} value={variable.mapping_expression} onChange={(event) => update(index, { ...variable, mapping_expression: event.target.value })} className={inputClass} /></label><label><EditorLabel>Origin</EditorLabel><input value={variable.origin} onChange={(event) => update(index, { ...variable, origin: event.target.value })} className={inputClass} /></label><label><EditorLabel>Controlled terms</EditorLabel><input value={variable.controlled_terms.join(", ")} onChange={(event) => update(index, { ...variable, controlled_terms: splitList(event.target.value) })} className={inputClass} /></label><label><EditorLabel>aCRF source label</EditorLabel><input value={variable.crf_source_label ?? ""} onChange={(event) => update(index, { ...variable, crf_source_label: event.target.value || null })} className={inputClass} /></label></div>
    <div className="mt-4 border-t border-white/[0.07] pt-3"><div className="flex items-center justify-between"><div><p className="text-[10px] font-black uppercase tracking-[0.12em] text-cyan-300">Value-level metadata</p><p className="mt-1 text-[11px] text-zinc-600">Each value-level row owns its own source lineage.</p></div><button type="button" onClick={() => update(index, { ...variable, value_level_metadata: [...variable.value_level_metadata, newVlm()] })} className="flex items-center gap-1 text-[10px] font-bold text-cyan-300"><Plus size={11} />VLM row</button></div>{variable.value_level_metadata.map((vlm, vlmIndex) => <div key={vlmIndex} className="mt-3 rounded-lg border border-cyan-500/15 bg-cyan-500/[0.03] p-3"><div className="grid gap-2 md:grid-cols-[1fr_1fr_100px_36px]"><input aria-label={`${variable.name} VLM ${vlmIndex + 1} where clause`} value={vlm.where_clause} onChange={(event) => update(index, { ...variable, value_level_metadata: replaceAt(variable.value_level_metadata, vlmIndex, { ...vlm, where_clause: event.target.value }) })} placeholder="Where clause" className={inputClass} /><input value={vlm.label} onChange={(event) => update(index, { ...variable, value_level_metadata: replaceAt(variable.value_level_metadata, vlmIndex, { ...vlm, label: event.target.value }) })} placeholder="Label" className={inputClass} /><select value={vlm.data_type} onChange={(event) => update(index, { ...variable, value_level_metadata: replaceAt(variable.value_level_metadata, vlmIndex, { ...vlm, data_type: event.target.value as SDTMDataType }) })} className={inputClass}><option>Char</option><option>Num</option></select><RemoveButton label={`Remove VLM ${vlmIndex + 1}`} onClick={() => update(index, { ...variable, value_level_metadata: variable.value_level_metadata.filter((_, itemIndex) => itemIndex !== vlmIndex) })} /></div><textarea rows={2} value={vlm.mapping_expression} onChange={(event) => update(index, { ...variable, value_level_metadata: replaceAt(variable.value_level_metadata, vlmIndex, { ...vlm, mapping_expression: event.target.value }) })} placeholder="Value-level mapping logic" className={`${inputClass} mt-2`} /><div className="mt-2"><SourceReferencesEditor value={vlm.sources} onChange={(sources) => update(index, { ...variable, value_level_metadata: replaceAt(variable.value_level_metadata, vlmIndex, { ...vlm, sources }) })} inventory={inventory} allowedDatasets={allowedDatasets} label={`${variable.name} VLM ${vlmIndex + 1} sources`} /></div></div>)}</div>
  </article>)}</div>;
}

export function newSourceVariable(name = "NEWVAR", source = ""): SDTMVariableDraft {
  return { name, label: "New SDTM variable", data_type: "Char", mapping_type: source ? "direct" : "assigned", sources: source ? [{ dataset: source, variable: "", role: "value" }] : [], origin: source ? "CRF" : "Assigned", mapping_expression: source ? "Direct" : "TODO: review assigned value", controlled_terms: [], value_level_metadata: [], crf_source_label: null };
}

export function normalizeRecordPlan(value: unknown): SDTMRecordPlan {
  const record = isRecord(value) ? value : {};
  return { steps: arrayValue<SDTMRecordStep>(record.steps).map(normalizeStep), output_step: stringValue(record.output_step, "") };
}

export function normalizeVariable(value: SDTMVariableDraft): SDTMVariableDraft {
  return { ...value, mapping_type: validMappingType(value.mapping_type) ? value.mapping_type : "direct", sources: arrayValue<SDTMSourceReference>(value.sources).map((item) => ({ dataset: stringValue(item.dataset, ""), variable: stringValue(item.variable, ""), role: roles.includes(item.role) ? item.role : "value" })), controlled_terms: arrayValue<string>(value.controlled_terms), value_level_metadata: arrayValue<SDTMValueLevelMetadataDraft>(value.value_level_metadata).map((item) => ({ ...item, data_type: item.data_type === "Num" ? "Num" : "Char", sources: arrayValue<SDTMSourceReference>(item.sources), controlled_terms: arrayValue<string>(item.controlled_terms) })) };
}

export function vlmMatrixIssues(domain: string, variables: SDTMVariableDraft[]): string[] {
  const issues: string[] = [];
  const findingSuffixes = ["TESTCD", "TEST", "ORRES", "ORRESU", "STRESC", "STRESN", "STRESU", "STNRLO", "STNRHI", "NRIND", "ORNRLO", "ORNRHI"];
  const wideFinding = variables.some((variable) => variable.name.endsWith("ORRES") && variable.mapping_type === "transpose" && variable.sources.length > 1);
  const required = variables.filter((variable) => variable.sources.length > 1 && (variable.mapping_type === "transpose" || (wideFinding && findingSuffixes.some((suffix) => variable.name.endsWith(suffix)))));
  let expectedConditions: Set<string> | null = null;
  for (const variable of required) {
    const label = `${domain}.${variable.name}`;
    if (!variable.value_level_metadata.length) { issues.push(`${label} has multi-source transpose lineage and needs VLM cells.`); continue; }
    const conditions = variable.value_level_metadata.map((item) => canonicalWhereClause(item.where_clause)).filter(Boolean);
    if (conditions.length !== variable.value_level_metadata.length) issues.push(`${label} has a VLM cell without a where clause.`);
    if (new Set(conditions).size !== conditions.length) issues.push(`${label} has duplicate VLM conditions.`);
    const covered = new Set(variable.value_level_metadata.flatMap((item) => item.sources).map(sourceIdentity));
    const missing = variable.sources.filter((source) => !covered.has(sourceIdentity(source)));
    if (missing.length) issues.push(`${label} has source lineage outside its VLM cells: ${missing.map((source) => `${source.dataset}.${source.variable}`).join(", ")}.`);
    variable.value_level_metadata.forEach((item, index) => {
      if (!item.label.trim()) issues.push(`${label} VLM ${index + 1} needs a label.`);
      if (!item.mapping_expression.trim()) issues.push(`${label} VLM ${index + 1} needs mapping logic.`);
      if (!item.sources.length && !allowsSourcelessVlmOrigin(item.origin)) issues.push(`${label} VLM ${index + 1} needs source lineage or an assigned/derived origin.`);
      if (!item.sources.length && (!item.mapping_expression.trim() || item.mapping_expression.trim().toLowerCase() === "direct")) issues.push(`${label} VLM ${index + 1} needs explicit assignment or derivation logic.`);
    });
    if (expectedConditions === null && conditions.length) expectedConditions = new Set(conditions);
    else if (expectedConditions && (conditions.some((item) => !expectedConditions!.has(item)) || expectedConditions.size !== conditions.length)) issues.push(`${label} VLM conditions do not align with the other transposed variables in ${domain}.`);
  }
  return issues;
}

function normalizeStep(step: SDTMRecordStep): SDTMRecordStep { return { ...operationDefaults(step.operation), ...step, operation: operations.includes(step.operation) ? step.operation : "read", inputs: arrayValue<string>(step.inputs), column_alignment: arrayValue<SDTMStackColumn>(step.column_alignment), join_keys: arrayValue<SDTMJoinKey>(step.join_keys), id_variables: arrayValue<string>(step.id_variables), value_variables: arrayValue<string>(step.value_variables), transpose_values: arrayValue<SDTMTransposeValue>(step.transpose_values), keys: arrayValue<string>(step.keys), order_by: arrayValue<string>(step.order_by), group_by: arrayValue<string>(step.group_by), aggregations: arrayValue<SDTMAggregation>(step.aggregations), review_notes: arrayValue<string>(step.review_notes) }; }
function newVlm(whereClause = "", dataset = ""): SDTMValueLevelMetadataDraft { return { where_clause: whereClause, label: "", data_type: "Char", origin: "CRF", mapping_expression: "", sources: dataset ? [{ dataset, variable: "", role: "value" }] : [], controlled_terms: [] }; }
function newRecordStep(operation: SDTMRecordOperation, index: number, allowed: string[], prior: SDTMRecordStep[]): SDTMRecordStep { const stepId = `${operation}_${index}`; const defaults = operationDefaults(operation); return { ...defaults, step_id: stepId, operation, description: `Review ${operation} operation`, output: stepId, source_dataset: operation === "read" ? allowed.find((source) => !prior.some((item) => item.source_dataset === source)) ?? allowed[0] ?? null : null, inputs: operation !== "read" && prior.length ? [prior.at(-1)!.step_id] : [] }; }
function operationDefaults(operation: SDTMRecordOperation): SDTMRecordStep { return { step_id: "", operation, description: "", output: "", inputs: [], source_dataset: null, column_alignment: [], left: null, right: null, join_type: operation === "join" ? "left" : null, join_keys: [], cardinality: operation === "join" ? "many_to_one" : null, id_variables: [], value_variables: [], name_variable: null, value_variable: null, transpose_values: [], condition: null, sas_condition: null, keys: [], order_by: [], keep: "first", group_by: [], aggregations: [], review_notes: [] }; }
function StepInputs({ value, options, onChange, label }: { value: string[]; options: string[]; onChange: (value: string[]) => void; label: string }) { return <div><EditorLabel>{label}</EditorLabel><div className="flex flex-wrap gap-2">{options.map((option) => <label key={option} className={`rounded-md border px-2 py-1.5 text-xs ${value.includes(option) ? "border-violet-500/40 bg-violet-500/10 text-violet-200" : "border-white/10 text-zinc-500"}`}><input type="checkbox" checked={value.includes(option)} onChange={(event) => onChange(event.target.checked ? [...value, option] : value.filter((item) => item !== option))} className="mr-2" />{option}</label>)}</div></div>; }
function StepSelect({ label, value, options, onChange }: { label: string; value: string | null; options: string[]; onChange: (value: string | null) => void }) { return <label><EditorLabel>{label}</EditorLabel><select value={value ?? ""} onChange={(event) => onChange(event.target.value || null)} className={inputClass}><option value="">Choose prior step</option>{options.map((option) => <option key={option}>{option}</option>)}</select></label>; }
function ListInput({ label, value, onChange }: { label: string; value: string[]; onChange: (value: string[]) => void }) { return <label><EditorLabel>{label}</EditorLabel><input value={value.join(", ")} onChange={(event) => onChange(splitList(event.target.value).map((item) => item.toUpperCase()))} placeholder="Comma-separated" className={inputClass} /></label>; }
function PairList({ label, leftLabel, rightLabel, values, onChange }: { label: string; leftLabel: string; rightLabel: string; values: SDTMJoinKey[]; onChange: (value: SDTMJoinKey[]) => void }) { return <div><div className="flex items-center justify-between"><EditorLabel>{label}</EditorLabel><button type="button" onClick={() => onChange([...values, { left: "", right: "" }])} className="text-[10px] font-bold text-violet-300">+ row</button></div>{values.map((item, index) => <div key={index} className="mt-2 grid gap-2 md:grid-cols-[1fr_1fr_36px]"><input aria-label={`${leftLabel} ${index + 1}`} value={item.left} onChange={(event) => onChange(replaceAt(values, index, { ...item, left: event.target.value.toUpperCase() }))} placeholder={leftLabel} className={inputClass} /><input aria-label={`${rightLabel} ${index + 1}`} value={item.right} onChange={(event) => onChange(replaceAt(values, index, { ...item, right: event.target.value.toUpperCase() }))} placeholder={rightLabel} className={inputClass} /><RemoveButton label={`Remove ${label} ${index + 1}`} onClick={() => onChange(values.filter((_, itemIndex) => itemIndex !== index))} /></div>)}</div>; }
function RemoveButton({ label, onClick }: { label: string; onClick: () => void }) { return <button type="button" aria-label={label} onClick={onClick} className="grid h-9 w-9 place-items-center rounded-md text-zinc-600 hover:bg-rose-500/10 hover:text-rose-300"><Trash2 size={13} /></button>; }
function EditorLabel({ children }: { children: ReactNode }) { return <span className="mb-1.5 block text-[10px] font-black uppercase tracking-[0.12em] text-zinc-500">{children}</span>; }
function replaceAt<T>(value: T[], index: number, next: T): T[] { return value.map((item, itemIndex) => itemIndex === index ? next : item); }
function splitList(value: string): string[] { return value.split(",").map((item) => item.trim()).filter(Boolean); }
function stringValue(value: unknown, fallback: string): string { return typeof value === "string" ? value : fallback; }
function arrayValue<T>(value: unknown): T[] { return Array.isArray(value) ? value as T[] : []; }
function isRecord(value: unknown): value is Record<string, unknown> { return Boolean(value) && typeof value === "object" && !Array.isArray(value); }
function validMappingType(value: unknown): value is SDTMMappingType { return typeof value === "string" && ["direct", "assigned", "derived", "coalesce", "lookup", "transpose", "aggregate"].includes(value); }
function canonicalWhereClause(value: string): string { return value.trim().toUpperCase().replace(/\s+/g, "").replace(/"/g, "'"); }
function sourceIdentity(source: SDTMSourceReference): string { return `${source.dataset.toUpperCase()}|${source.variable.toUpperCase()}`; }
function allowsSourcelessVlmOrigin(value: string): boolean { const normalized = value.trim().toLowerCase(); return ["assigned", "derived", "protocol", "system", "sponsor"].some((token) => normalized.includes(token)); }
