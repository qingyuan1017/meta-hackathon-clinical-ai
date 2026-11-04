"use client";

import { useMemo, useState, type ReactNode } from "react";
import { AlertTriangle, Database, Plus, Save, Trash2 } from "lucide-react";
import { Button } from "./ui/button";

type SourceType = "raw" | "sdtm";
type DataType = "text" | "integer" | "decimal" | "date" | "datetime" | "boolean" | "coded" | "unknown";

interface Provenance {
  file: string;
  sheet: string | null;
  row: number | null;
  json_path: string | null;
}

interface SourceVariable {
  name: string;
  label: string;
  data_type: DataType;
  length: number | null;
  format: string | null;
  required: boolean;
  codelist: string | null;
  form_id: string | null;
  question: string | null;
  provenance: Provenance;
}

interface SourceDataset {
  name: string;
  label: string;
  source_type: SourceType;
  structure: string;
  key_variables: string[];
  variables: SourceVariable[];
  provenance: Provenance;
}

interface SourceCodeList {
  name: string;
  values: string[];
}

export interface EDCSourceSpecificationDraft extends Record<string, unknown> {
  study_name: string;
  datasets: SourceDataset[];
  codelists: SourceCodeList[];
  assumptions: string[];
  unresolved_items: string[];
}

const inputClass = "focus-ring min-h-9 w-full rounded-md border border-white/10 bg-[#101012] px-2.5 py-2 text-xs text-zinc-200 placeholder:text-zinc-600";

export function EDCSourceReviewEditor({ value, onChange, onApprove, saving, error }: {
  value: Record<string, unknown>;
  onChange: (value: EDCSourceSpecificationDraft) => void;
  onApprove: (value: EDCSourceSpecificationDraft) => void;
  saving: boolean;
  error?: string | null;
}) {
  const specification = normalizeSpecification(value);
  const [selectedDataset, setSelectedDataset] = useState(specification.datasets[0]?.name ?? "");
  const activeDataset = specification.datasets.find((dataset) => dataset.name === selectedDataset) ?? specification.datasets[0];
  const issues = reviewIssues(specification);

  const update = (mutate: (next: EDCSourceSpecificationDraft) => void) => {
    const next = structuredClone(specification);
    mutate(next);
    onChange(next);
  };

  const addDataset = () => update((next) => {
    const name = uniqueName("NEW_DATASET", next.datasets.map((dataset) => dataset.name));
    next.datasets.push({
      name,
      label: "New source dataset",
      source_type: "raw",
      structure: "Not specified",
      key_variables: [],
      variables: [newVariable("NEW_VARIABLE", "User review")],
      provenance: newProvenance("User review"),
    });
    setSelectedDataset(name);
  });

  const addVariable = () => {
    if (!activeDataset) return;
    update((next) => {
      const dataset = next.datasets.find((item) => item.name === activeDataset.name);
      if (!dataset) return;
      dataset.variables.push(newVariable(uniqueName("NEW_VARIABLE", dataset.variables.map((variable) => variable.name)), dataset.provenance.file));
    });
  };

  const codelistNames = useMemo(() => new Set(specification.codelists.map((item) => item.name)), [specification.codelists]);

  return (
    <div className="space-y-5">
      <div className="rounded-xl border border-amber-500/25 bg-amber-500/[0.08] p-4">
        <p className="text-xs font-black uppercase tracking-[0.14em] text-amber-200">Review gate 1 of 3</p>
        <p className="mt-1 text-base font-bold text-amber-100">EDC source review required</p>
        <p className="mt-1 text-sm leading-6 text-amber-100/80">The uploaded EDC was normalized into a complete source-schema draft. Confirm dataset and variable identifiers before SDTM domain mapping begins.</p>
      </div>

      <section className="rounded-xl border border-white/10 bg-white/[0.02] p-4">
        <label><EditorLabel>Study name</EditorLabel><input value={specification.study_name} onChange={(event) => update((next) => { next.study_name = event.target.value; })} className={inputClass} /></label>
      </section>

      <div className="flex flex-wrap items-center gap-2">
        {specification.datasets.map((dataset) => <button type="button" key={dataset.name} onClick={() => setSelectedDataset(dataset.name)} className={`focus-ring rounded-lg border px-3 py-2 font-mono text-xs font-bold ${activeDataset?.name === dataset.name ? "border-violet-500/40 bg-violet-500/10 text-violet-200" : "border-white/10 bg-white/[0.02] text-zinc-500"}`}>{dataset.name}</button>)}
        <Button type="button" variant="outline" size="sm" onClick={addDataset}><Plus size={14} />Dataset</Button>
      </div>

      {activeDataset ? (
        <section className="overflow-hidden rounded-xl border border-white/10 bg-[#141416]">
          <div className="grid gap-3 border-b border-white/10 p-4 lg:grid-cols-[160px_minmax(180px,1fr)_130px_minmax(180px,1fr)_auto]">
            <label><EditorLabel>Dataset</EditorLabel><input value={activeDataset.name} onChange={(event) => update((next) => {
              const dataset = next.datasets.find((item) => item.name === activeDataset.name);
              if (!dataset) return;
              dataset.name = event.target.value.toUpperCase();
              setSelectedDataset(dataset.name);
            })} className={`${inputClass} font-mono font-bold text-violet-200`} /></label>
            <label><EditorLabel>Label</EditorLabel><input value={activeDataset.label} onChange={(event) => updateDataset(update, activeDataset.name, "label", event.target.value)} className={inputClass} /></label>
            <label><EditorLabel>Source type</EditorLabel><select value={activeDataset.source_type} onChange={(event) => updateDataset(update, activeDataset.name, "source_type", event.target.value)} className={inputClass}><option value="raw">Raw</option><option value="sdtm">Existing SDTM</option></select></label>
            <label><EditorLabel>Structure</EditorLabel><input value={activeDataset.structure} onChange={(event) => updateDataset(update, activeDataset.name, "structure", event.target.value)} className={inputClass} /></label>
            <button type="button" aria-label={`Remove ${activeDataset.name}`} onClick={() => update((next) => {
              next.datasets = next.datasets.filter((dataset) => dataset.name !== activeDataset.name);
              setSelectedDataset(next.datasets[0]?.name ?? "");
            })} className="mt-5 grid h-9 w-9 place-items-center rounded-md text-zinc-600 hover:bg-rose-500/10 hover:text-rose-300"><Trash2 size={15} /></button>
          </div>
          <div className="grid gap-3 border-b border-white/10 px-4 py-3 md:grid-cols-[minmax(220px,1fr)_minmax(180px,1fr)_120px_minmax(240px,1fr)]">
            <label><EditorLabel>Dataset source file</EditorLabel><input value={activeDataset.provenance.file} onChange={(event) => updateDataset(update, activeDataset.name, "provenance", { ...activeDataset.provenance, file: event.target.value })} className={inputClass} /></label>
            <label><EditorLabel>Dataset source sheet</EditorLabel><input value={activeDataset.provenance.sheet ?? ""} onChange={(event) => updateDataset(update, activeDataset.name, "provenance", { ...activeDataset.provenance, sheet: event.target.value || null })} className={inputClass} /></label>
            <label><EditorLabel>Dataset source row</EditorLabel><input type="number" min={1} value={activeDataset.provenance.row ?? ""} onChange={(event) => updateDataset(update, activeDataset.name, "provenance", { ...activeDataset.provenance, row: event.target.value ? Number(event.target.value) : null })} className={inputClass} /></label>
            <label><EditorLabel>JSON path</EditorLabel><input value={activeDataset.provenance.json_path ?? ""} readOnly placeholder="Not a JSON source" className={`${inputClass} font-mono text-zinc-400`} /></label>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 px-4 py-3">
            <p className="text-xs text-zinc-500">Check Key for variables that identify records. Provenance remains editable when the agent could not resolve a location.</p>
            <Button type="button" variant="outline" size="sm" onClick={addVariable}><Plus size={14} />Variable</Button>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1700px] border-collapse text-left text-xs">
              <thead className="bg-white/[0.03] text-[10px] uppercase tracking-wider text-zinc-500"><tr>{["Variable", "Label", "Type", "Length / format", "Required / key", "Codelist", "Form / question", "Provenance", ""].map((heading) => <th key={heading} className="border-b border-r border-white/10 px-3 py-2.5 font-black last:border-r-0">{heading}</th>)}</tr></thead>
              <tbody>{activeDataset.variables.map((variable, index) => <VariableRow key={`${variable.name}-${index}`} variable={variable} isKey={activeDataset.key_variables.includes(variable.name)} codelistNames={codelistNames} onUpdate={(key, nextValue) => update((next) => {
                const dataset = next.datasets.find((item) => item.name === activeDataset.name);
                const target = dataset?.variables[index];
                if (!dataset || !target) return;
                const previousName = target.name;
                (target as unknown as Record<string, unknown>)[key] = nextValue;
                if (key === "name") dataset.key_variables = dataset.key_variables.map((item) => item === previousName ? String(nextValue) : item);
              })} onToggleKey={(checked) => update((next) => {
                const dataset = next.datasets.find((item) => item.name === activeDataset.name);
                if (!dataset) return;
                dataset.key_variables = checked ? Array.from(new Set([...dataset.key_variables, variable.name])) : dataset.key_variables.filter((item) => item !== variable.name);
              })} onRemove={() => update((next) => {
                const dataset = next.datasets.find((item) => item.name === activeDataset.name);
                if (!dataset) return;
                dataset.variables.splice(index, 1);
                dataset.key_variables = dataset.key_variables.filter((item) => item !== variable.name);
              })} />)}</tbody>
            </table>
          </div>
        </section>
      ) : <div className="grid min-h-52 place-items-center rounded-xl border border-dashed border-white/15 text-sm text-zinc-500">Add at least one source dataset.</div>}

      <section className="space-y-3 rounded-xl border border-white/10 bg-white/[0.02] p-4">
        <div className="flex items-center justify-between"><div><p className="text-xs font-black uppercase tracking-[0.12em] text-zinc-400">Source codelists</p><p className="mt-1 text-xs text-zinc-600">Variables may reference one of these names.</p></div><Button type="button" variant="outline" size="sm" onClick={() => update((next) => { next.codelists.push({ name: uniqueName("NEW_CODELIST", next.codelists.map((item) => item.name)), values: [] }); })}><Plus size={14} />Codelist</Button></div>
        {specification.codelists.map((codelist, index) => <div key={`${codelist.name}-${index}`} className="grid gap-2 md:grid-cols-[220px_minmax(0,1fr)_36px]"><input value={codelist.name} onChange={(event) => update((next) => {
          const previous = next.codelists[index].name;
          next.codelists[index].name = event.target.value;
          next.datasets.forEach((dataset) => dataset.variables.forEach((variable) => { if (variable.codelist === previous) variable.codelist = event.target.value; }));
        })} className={inputClass} /><input value={codelist.values.join(", ")} onChange={(event) => update((next) => { next.codelists[index].values = splitList(event.target.value); })} placeholder="Allowed values" className={inputClass} /><button type="button" aria-label={`Remove ${codelist.name}`} onClick={() => update((next) => {
          const removed = next.codelists[index].name;
          next.codelists.splice(index, 1);
          next.datasets.forEach((dataset) => dataset.variables.forEach((variable) => { if (variable.codelist === removed) variable.codelist = null; }));
        })} className="grid h-9 w-9 place-items-center rounded-md text-zinc-600 hover:bg-rose-500/10 hover:text-rose-300"><Trash2 size={14} /></button></div>)}
      </section>

      <section className="grid gap-4 md:grid-cols-2">
        <label><EditorLabel>Assumptions — one per line</EditorLabel><textarea value={specification.assumptions.join("\n")} onChange={(event) => update((next) => { next.assumptions = splitLines(event.target.value); })} className={`${inputClass} min-h-28`} /></label>
        <label><EditorLabel>Unresolved items — one per line</EditorLabel><textarea value={specification.unresolved_items.join("\n")} onChange={(event) => update((next) => { next.unresolved_items = splitLines(event.target.value); })} className={`${inputClass} min-h-28`} /></label>
      </section>

      <div className="sticky bottom-3 z-20 flex flex-col gap-3 rounded-xl border border-white/15 bg-[#161619]/95 p-4 shadow-2xl backdrop-blur sm:flex-row sm:items-center sm:justify-between">
        <div>{issues.length ? <p className="flex items-center gap-2 text-xs font-bold text-amber-200"><AlertTriangle size={15} />{issues[0]}{issues.length > 1 ? ` (+${issues.length - 1} more)` : ""}</p> : <p className="flex items-center gap-2 text-xs font-bold text-emerald-300"><Database size={15} />Source references are ready for backend validation.</p>}{error && <p className="mt-1 text-xs text-rose-300">{error}</p>}</div>
        <Button type="button" variant="clinical" onClick={() => onApprove(specification)} disabled={saving || issues.length > 0}><Save size={16} />{saving ? "Approving and resuming…" : "Approve"}</Button>
      </div>
    </div>
  );
}

function VariableRow({ variable, isKey, codelistNames, onUpdate, onToggleKey, onRemove }: { variable: SourceVariable; isKey: boolean; codelistNames: Set<string>; onUpdate: (key: keyof SourceVariable, value: unknown) => void; onToggleKey: (checked: boolean) => void; onRemove: () => void }) {
  return <tr className="align-top hover:bg-white/[0.015]"><td className="border-b border-r border-white/[0.07] p-2"><input value={variable.name} onChange={(event) => onUpdate("name", event.target.value.toUpperCase())} className={`${inputClass} font-mono font-bold text-violet-200`} /></td><td className="border-b border-r border-white/[0.07] p-2"><input value={variable.label} onChange={(event) => onUpdate("label", event.target.value)} className={inputClass} /></td><td className="border-b border-r border-white/[0.07] p-2"><select value={variable.data_type} onChange={(event) => onUpdate("data_type", event.target.value)} className={inputClass}>{["text", "integer", "decimal", "date", "datetime", "boolean", "coded", "unknown"].map((type) => <option key={type} value={type}>{type}</option>)}</select></td><td className="min-w-44 border-b border-r border-white/[0.07] p-2"><input type="number" min={1} value={variable.length ?? ""} onChange={(event) => onUpdate("length", event.target.value ? Number(event.target.value) : null)} placeholder="Length" className={inputClass} /><input value={variable.format ?? ""} onChange={(event) => onUpdate("format", event.target.value || null)} placeholder="Format" className={`${inputClass} mt-1`} /></td><td className="border-b border-r border-white/[0.07] p-2"><label className="flex items-center gap-2 py-1 text-zinc-300"><input type="checkbox" checked={variable.required} onChange={(event) => onUpdate("required", event.target.checked)} />Required</label><label className="flex items-center gap-2 py-1 text-zinc-300"><input type="checkbox" checked={isKey} onChange={(event) => onToggleKey(event.target.checked)} />Key</label></td><td className="border-b border-r border-white/[0.07] p-2"><input value={variable.codelist ?? ""} onChange={(event) => onUpdate("codelist", event.target.value || null)} placeholder="Codelist" className={`${inputClass} ${variable.codelist && !codelistNames.has(variable.codelist) ? "border-amber-500/50" : ""}`} /></td><td className="min-w-52 border-b border-r border-white/[0.07] p-2"><input value={variable.form_id ?? ""} onChange={(event) => onUpdate("form_id", event.target.value || null)} placeholder="Form ID" className={inputClass} /><input value={variable.question ?? ""} onChange={(event) => onUpdate("question", event.target.value || null)} placeholder="Question / prompt" className={`${inputClass} mt-1`} /></td><td className="min-w-60 border-b border-r border-white/[0.07] p-2"><input value={variable.provenance.file} onChange={(event) => onUpdate("provenance", { ...variable.provenance, file: event.target.value })} placeholder="File" className={inputClass} /><input value={variable.provenance.json_path ?? ""} readOnly placeholder="JSON path" className={`${inputClass} mt-1 font-mono text-zinc-500`} /><div className="mt-1 grid grid-cols-[1fr_90px] gap-1"><input value={variable.provenance.sheet ?? ""} onChange={(event) => onUpdate("provenance", { ...variable.provenance, sheet: event.target.value || null })} placeholder="Sheet" className={inputClass} /><input type="number" min={1} value={variable.provenance.row ?? ""} onChange={(event) => onUpdate("provenance", { ...variable.provenance, row: event.target.value ? Number(event.target.value) : null })} placeholder="Row" className={inputClass} /></div></td><td className="border-b border-white/[0.07] p-2"><button type="button" aria-label={`Remove ${variable.name}`} onClick={onRemove} className="grid h-9 w-9 place-items-center rounded-md text-zinc-600 hover:bg-rose-500/10 hover:text-rose-300"><Trash2 size={14} /></button></td></tr>;
}

function normalizeSpecification(value: Record<string, unknown>): EDCSourceSpecificationDraft {
  return {
    ...value,
    study_name: stringValue(value.study_name, "Untitled study"),
    datasets: arrayValue<SourceDataset>(value.datasets).map((dataset) => ({
      ...dataset,
      source_type: dataset.source_type === "sdtm" ? "sdtm" : "raw",
      key_variables: arrayValue<string>(dataset.key_variables),
      variables: arrayValue<SourceVariable>(dataset.variables).map((variable) => ({ ...variable, provenance: normalizeProvenance(variable.provenance) })),
      provenance: normalizeProvenance(dataset.provenance),
    })),
    codelists: arrayValue<SourceCodeList>(value.codelists).map((item) => ({ ...item, values: arrayValue<string>(item.values) })),
    assumptions: arrayValue<string>(value.assumptions),
    unresolved_items: arrayValue<string>(value.unresolved_items),
  };
}

function reviewIssues(specification: EDCSourceSpecificationDraft): string[] {
  const issues: string[] = [];
  if (!specification.study_name.trim()) issues.push("Study name is required.");
  if (!specification.datasets.length) issues.push("Add at least one source dataset.");
  const datasetNames = specification.datasets.map((dataset) => dataset.name.trim().toUpperCase());
  if (new Set(datasetNames).size !== datasetNames.length) issues.push("Source dataset names must be unique.");
  const codelists = new Set(specification.codelists.map((item) => item.name.trim().toUpperCase()));
  specification.datasets.forEach((dataset) => {
    if (!dataset.name.trim()) issues.push("Every source dataset needs a name.");
    if (!dataset.provenance.file.trim()) issues.push(`${dataset.name || "[unnamed dataset]"} needs source provenance.`);
    if (!dataset.variables.length) issues.push(`${dataset.name || "[unnamed dataset]"} needs at least one variable.`);
    const variables = dataset.variables.map((variable) => variable.name.trim().toUpperCase());
    if (new Set(variables).size !== variables.length) issues.push(`${dataset.name} has duplicate variable names.`);
    dataset.key_variables.forEach((key) => { if (!variables.includes(key.trim().toUpperCase())) issues.push(`${dataset.name} key ${key} does not reference a variable.`); });
    dataset.variables.forEach((variable) => {
      if (!variable.name.trim()) issues.push(`${dataset.name} has a variable without a name.`);
      if (!variable.provenance.file.trim()) issues.push(`${dataset.name}.${variable.name || "[unnamed]"} needs source provenance.`);
      if (variable.codelist && !codelists.has(variable.codelist.trim().toUpperCase())) issues.push(`${dataset.name}.${variable.name} references an unknown codelist.`);
    });
  });
  return Array.from(new Set(issues));
}

function updateDataset(update: (mutate: (next: EDCSourceSpecificationDraft) => void) => void, name: string, key: keyof SourceDataset, value: unknown) { update((next) => { const dataset = next.datasets.find((item) => item.name === name); if (dataset) (dataset as unknown as Record<string, unknown>)[key] = value; }); }
function newVariable(name: string, file: string): SourceVariable { return { name, label: name, data_type: "unknown", length: null, format: null, required: false, codelist: null, form_id: null, question: null, provenance: newProvenance(file) }; }
function newProvenance(file: string): Provenance { return { file, sheet: null, row: null, json_path: null }; }
function normalizeProvenance(value: unknown): Provenance { if (!isRecord(value)) return newProvenance("User review"); return { file: stringValue(value.file, "User review"), sheet: typeof value.sheet === "string" ? value.sheet : null, row: typeof value.row === "number" ? value.row : null, json_path: typeof value.json_path === "string" ? value.json_path : null }; }
function uniqueName(prefix: string, values: string[]): string { const used = new Set(values.map((value) => value.toUpperCase())); let index = 1; let candidate = prefix; while (used.has(candidate.toUpperCase())) candidate = `${prefix}_${++index}`; return candidate; }
function splitList(value: string): string[] { return value.split(",").map((item) => item.trim()).filter(Boolean); }
function splitLines(value: string): string[] { return value.split("\n").map((item) => item.trim()).filter(Boolean); }
function stringValue(value: unknown, fallback: string): string { return typeof value === "string" ? value : fallback; }
function arrayValue<T>(value: unknown): T[] { return Array.isArray(value) ? value as T[] : []; }
function isRecord(value: unknown): value is Record<string, unknown> { return Boolean(value) && typeof value === "object" && !Array.isArray(value); }
function EditorLabel({ children }: { children: ReactNode }) { return <span className="mb-1.5 block text-[10px] font-black uppercase tracking-[0.12em] text-zinc-500">{children}</span>; }
