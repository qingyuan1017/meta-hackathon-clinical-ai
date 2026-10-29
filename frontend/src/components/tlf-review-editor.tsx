"use client";

import { useMemo, useState } from "react";
import { ArrowDown, ArrowUp, Copy, Plus, Save, Trash2 } from "lucide-react";
import { Button } from "./ui/button";

type OutputType = "table" | "listing" | "figure";
type ReviewStage = "inventory" | "analysis" | "programming";
interface TLFColumn { column_id: string; heading: string; source: string; statistic: string; format: string; }
interface TLFRow { row_id: string; label: string; source: string; statistic: string; condition: string; format: string; }
interface SourceVariable { dataset: string; variable: string; role: string; derivation: string; }
interface FigureSpec { geometry: string; x_axis: string; y_axis: string; group: string; panel: string; }
interface TLFOutput {
  output_id: string; output_type: OutputType; title: string; section: string; purpose: string;
  population: string; population_filter: string; analysis_datasets: string[]; source_variables: SourceVariable[];
  selection_criteria: string[]; treatment_variable: string; analysis_method: string; columns: TLFColumn[];
  rows: TLFRow[]; figure: FigureSpec | null; sort_order: string[]; footnotes: string[]; display_notes: string[];
  programming_notes: string[]; source_reference: string; readiness: "ready" | "blocked"; blocking_items: string[];
}
interface TLFProgram { output_id: string; input_datasets: string[]; derivation_steps: string[]; r_code: string; sas_code: string; review_notes: string[]; }
export interface TLFPlanDraft extends Record<string, unknown> {
  study_name: string; analysis_standard: string; outputs: TLFOutput[]; programs: TLFProgram[];
  assumptions: string[]; unresolved_items: string[];
}

const inputClass = "focus-ring h-9 w-full rounded-md border border-white/15 bg-[#111113] px-2.5 text-xs text-zinc-200";
const areaClass = "focus-ring min-h-20 w-full rounded-md border border-white/15 bg-[#111113] px-2.5 py-2 text-xs leading-5 text-zinc-200";

export function TLFReviewEditor({ value, onChange, onSave, saving, error }: {
  value: Record<string, unknown>; onChange: (value: TLFPlanDraft) => void; onSave: (value: TLFPlanDraft) => void; saving: boolean; error?: string;
}) {
  const plan = useMemo(() => normalizePlan(value), [value]);
  const [selected, setSelected] = useState(plan.outputs[0]?.output_id ?? "");
  const [filter, setFilter] = useState<"all" | OutputType>("all");
  const [stage, setStage] = useState<ReviewStage>("inventory");
  const activeIndex = Math.max(0, plan.outputs.findIndex((item) => item.output_id === selected));
  const active = plan.outputs[activeIndex];
  const filtered = plan.outputs.filter((item) => filter === "all" || item.output_type === filter);

  const update = (mutate: (next: TLFPlanDraft) => void) => { const next = structuredClone(plan); mutate(next); onChange(next); };
  const updateOutput = (key: keyof TLFOutput, nextValue: unknown) => update((next) => {
    const previousId = next.outputs[activeIndex].output_id;
    (next.outputs[activeIndex] as unknown as Record<string, unknown>)[key] = nextValue;
    if (key === "output_id") {
      const linked = next.programs.find((item) => item.output_id === previousId);
      if (linked) linked.output_id = String(nextValue);
      setSelected(String(nextValue));
    }
  });
  const programIndex = active ? plan.programs.findIndex((item) => item.output_id === active.output_id) : -1;
  const program = programIndex >= 0 ? plan.programs[programIndex] : undefined;
  const updateProgram = (key: keyof TLFProgram, nextValue: unknown) => update((next) => {
    let index = next.programs.findIndex((item) => item.output_id === active.output_id);
    if (index < 0) { next.programs.push(newProgram(active.output_id)); index = next.programs.length - 1; }
    (next.programs[index] as unknown as Record<string, unknown>)[key] = nextValue;
  });

  const addOutput = () => update((next) => {
    const id = uniqueId(next.outputs, "T-NEW"); next.outputs.push(newOutput(id)); next.programs.push(newProgram(id)); setSelected(id);
  });
  const duplicate = () => update((next) => {
    const copy = structuredClone(next.outputs[activeIndex]); const id = uniqueId(next.outputs, `${copy.output_id}-COPY`); copy.output_id = id;
    copy.title = `${copy.title} (copy)`; next.outputs.splice(activeIndex + 1, 0, copy);
    const sourceProgram = next.programs.find((item) => item.output_id === active.output_id); next.programs.push(sourceProgram ? { ...structuredClone(sourceProgram), output_id: id } : newProgram(id)); setSelected(id);
  });
  const remove = () => update((next) => {
    const [removed] = next.outputs.splice(activeIndex, 1); next.programs = next.programs.filter((item) => item.output_id !== removed.output_id);
    setSelected(next.outputs[Math.min(activeIndex, next.outputs.length - 1)]?.output_id ?? "");
  });
  const move = (offset: number) => update((next) => {
    const target = activeIndex + offset; if (target < 0 || target >= next.outputs.length) return;
    [next.outputs[activeIndex], next.outputs[target]] = [next.outputs[target], next.outputs[activeIndex]];
  });

  return <div className="space-y-5">
    <div className="rounded-xl border border-violet-500/20 bg-violet-500/[0.06] p-4">
      <p className="text-xs font-black uppercase tracking-[0.14em] text-violet-300">TLF review workspace</p>
      <p className="mt-1 text-sm text-zinc-300">Review source-grounded outputs, analysis metadata, display rules, and non-executed program scaffolds. Saving revalidates the full plan and rebuilds every artifact.</p>
    </div>
    <div className="flex flex-wrap gap-2 border-b border-white/10" role="tablist" aria-label="TLF review stages">
      {([
        ["inventory", "1 · Output inventory"],
        ["analysis", "2 · Analysis & display"],
        ["programming", "3 · Programming augmentation"],
      ] as const).map(([value, label]) => <button key={value} type="button" role="tab" aria-selected={stage === value} onClick={() => setStage(value)} className={`focus-ring rounded-t-lg px-4 py-2.5 text-sm font-bold ${stage === value ? "border-b-2 border-violet-500 text-violet-300" : "text-zinc-500 hover:text-zinc-300"}`}>{label}</button>)}
    </div>
    <div className="grid gap-5 xl:grid-cols-[260px_minmax(0,1fr)]">
      <aside className="space-y-3 rounded-xl border border-white/10 bg-white/[0.02] p-3">
        <div className="flex gap-2"><select aria-label="Filter outputs" value={filter} onChange={(event) => setFilter(event.target.value as typeof filter)} className={inputClass}><option value="all">All outputs</option><option value="table">Tables</option><option value="listing">Listings</option><option value="figure">Figures</option></select><Button type="button" size="sm" variant="outline" onClick={addOutput}><Plus size={14} /></Button></div>
        <div className="space-y-2">{filtered.map((item) => <button type="button" key={item.output_id} onClick={() => setSelected(item.output_id)} className={`w-full rounded-lg border p-3 text-left ${selected === item.output_id ? "border-violet-500/50 bg-violet-500/10" : "border-white/10 bg-black/10"}`}><div className="flex items-center justify-between gap-2"><span className="font-mono text-xs font-black text-zinc-100">{item.output_id}</span><span className={`rounded-full px-2 py-0.5 text-[9px] font-black uppercase ${item.readiness === "ready" ? "bg-emerald-500/15 text-emerald-300" : "bg-amber-500/15 text-amber-300"}`}>{item.readiness}</span></div><p className="mt-1 line-clamp-2 text-xs text-zinc-400">{item.title}</p></button>)}</div>
      </aside>
      {active ? <main className="space-y-5">
        {stage === "inventory" && <>
          <div className="flex flex-wrap items-center justify-between gap-2"><div className="flex gap-2"><Button type="button" size="sm" variant="outline" onClick={() => move(-1)}><ArrowUp size={14} /></Button><Button type="button" size="sm" variant="outline" onClick={() => move(1)}><ArrowDown size={14} /></Button><Button type="button" size="sm" variant="outline" onClick={duplicate}><Copy size={14} />Duplicate</Button></div><Button type="button" size="sm" variant="danger" onClick={remove}><Trash2 size={14} />Remove</Button></div>
          <Section title="Output overview"><div className="grid gap-3 md:grid-cols-3"><Field label="Output ID" value={active.output_id} onChange={(value) => updateOutput("output_id", value)} /><label><Label text="Type" /><select value={active.output_type} onChange={(event) => updateOutput("output_type", event.target.value)} className={inputClass}><option value="table">Table</option><option value="listing">Listing</option><option value="figure">Figure</option></select></label><Field label="Section" value={active.section} onChange={(value) => updateOutput("section", value)} /></div><Field label="Title" value={active.title} onChange={(value) => updateOutput("title", value)} /><Text label="Purpose" value={active.purpose} onChange={(value) => updateOutput("purpose", value)} /><Field label="SAP / protocol reference" value={active.source_reference} onChange={(value) => updateOutput("source_reference", value)} /></Section>
        </>}
        {stage === "analysis" && <>
          <Section title="Population and analysis"><div className="grid gap-3 md:grid-cols-2"><Field label="Population" value={active.population} onChange={(value) => updateOutput("population", value)} /><Field label="Population filter" value={active.population_filter} onChange={(value) => updateOutput("population_filter", value)} /><Field label="Treatment variable" value={active.treatment_variable} onChange={(value) => updateOutput("treatment_variable", value)} /><Field label="Analysis datasets (comma-separated)" value={active.analysis_datasets.join(", ")} onChange={(value) => updateOutput("analysis_datasets", splitComma(value))} /></div><Text label="Analysis method" value={active.analysis_method} onChange={(value) => updateOutput("analysis_method", value)} /><Text label="Selection criteria (one per line)" value={active.selection_criteria.join("\n")} onChange={(value) => updateOutput("selection_criteria", splitLines(value))} /><SourceVariables value={active.source_variables} onChange={(value) => updateOutput("source_variables", value)} /></Section>
          <Section title="Display specification">{active.output_type === "figure" ? <FigureEditor value={active.figure ?? newFigure()} onChange={(value) => updateOutput("figure", value)} /> : <DisplayGrid type={active.output_type} columns={active.columns} rows={active.rows} onColumns={(value) => updateOutput("columns", value)} onRows={(value) => updateOutput("rows", value)} />}<Text label="Sort order (one per line)" value={active.sort_order.join("\n")} onChange={(value) => updateOutput("sort_order", splitLines(value))} /><Text label="Footnotes (one per line)" value={active.footnotes.join("\n")} onChange={(value) => updateOutput("footnotes", splitLines(value))} /></Section>
        </>}
        {stage === "programming" && <Section title="Programming scaffolds"><Field label="Input datasets (comma-separated)" value={(program?.input_datasets ?? []).join(", ")} onChange={(value) => updateProgram("input_datasets", splitComma(value))} /><Text label="Derivation steps (one per line)" value={(program?.derivation_steps ?? []).join("\n")} onChange={(value) => updateProgram("derivation_steps", splitLines(value))} /><Text label="R scaffold" value={program?.r_code ?? ""} onChange={(value) => updateProgram("r_code", value)} mono /><Text label="SAS scaffold" value={program?.sas_code ?? ""} onChange={(value) => updateProgram("sas_code", value)} mono /></Section>}
        <Section title="Readiness blockers"><Text label="Blocking items (one per line)" value={active.blocking_items.join("\n")} onChange={(value) => updateOutput("blocking_items", splitLines(value))} />{active.readiness === "blocked" && <p className="text-xs text-amber-300">This output remains in the package but is marked blocked until its TODOs and blocking items are resolved.</p>}</Section>
      </main> : <div className="grid min-h-64 place-items-center rounded-xl border border-dashed border-white/15 text-sm text-zinc-500">Add an output to begin review.</div>}
    </div>
    {error && <div className="rounded-lg border border-rose-500/20 bg-rose-500/10 p-3 text-sm text-rose-300">{error}</div>}
    <Button variant="clinical" onClick={() => onSave(plan)} disabled={saving || !plan.outputs.length}><Save size={16} />{saving ? "Validating and rebuilding…" : "Save review and rebuild artifacts"}</Button>
  </div>;
}

function Section({ title, children }: { title: string; children: React.ReactNode }) { return <section className="space-y-3 rounded-xl border border-white/10 bg-white/[0.02] p-4"><h3 className="text-sm font-black text-zinc-100">{title}</h3>{children}</section>; }
function Label({ text }: { text: string }) { return <span className="mb-1.5 block text-[10px] font-black uppercase tracking-wider text-zinc-500">{text}</span>; }
function Field({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) { return <label><Label text={label} /><input value={value} onChange={(event) => onChange(event.target.value)} className={inputClass} /></label>; }
function Text({ label, value, onChange, mono = false }: { label: string; value: string; onChange: (value: string) => void; mono?: boolean }) { return <label><Label text={label} /><textarea value={value} onChange={(event) => onChange(event.target.value)} className={`${areaClass} ${mono ? "font-mono" : ""}`} /></label>; }

function SourceVariables({ value, onChange }: { value: SourceVariable[]; onChange: (value: SourceVariable[]) => void }) { return <div><div className="mb-2 flex items-center justify-between"><Label text="Source variables" /><Button type="button" size="sm" variant="outline" onClick={() => onChange([...value, { dataset: "", variable: "", role: "Analysis input", derivation: "Direct" }])}><Plus size={13} />Add</Button></div>{value.map((item, index) => <div key={index} className="mb-2 grid gap-2 md:grid-cols-[1fr_1fr_1fr_1fr_32px]">{(["dataset", "variable", "role", "derivation"] as const).map((key) => <input key={key} aria-label={`Source ${key}`} value={item[key]} placeholder={key} onChange={(event) => { const next = structuredClone(value); next[index][key] = event.target.value; onChange(next); }} className={inputClass} />)}<button type="button" aria-label="Remove source variable" onClick={() => onChange(value.filter((_, itemIndex) => itemIndex !== index))} className="text-rose-300"><Trash2 size={14} /></button></div>)}</div>; }
function DisplayGrid({ type, columns, rows, onColumns, onRows }: { type: OutputType; columns: TLFColumn[]; rows: TLFRow[]; onColumns: (value: TLFColumn[]) => void; onRows: (value: TLFRow[]) => void }) { return <div className="space-y-4"><ArrayEditor label="Columns" items={columns} fields={["column_id", "heading", "source", "statistic", "format"]} onChange={onColumns} create={() => ({ column_id: `COL${columns.length + 1}`, heading: "New column", source: "TODO: confirm source", statistic: "", format: "TODO: confirm format" })} />{type === "table" && <ArrayEditor label="Rows" items={rows} fields={["row_id", "label", "source", "statistic", "condition", "format"]} onChange={onRows} create={() => ({ row_id: `ROW${rows.length + 1}`, label: "New row", source: "TODO: confirm source", statistic: "", condition: "", format: "TODO: confirm format" })} />}</div>; }
function ArrayEditor<T extends Record<string, string>>({ label, items, fields, onChange, create }: { label: string; items: T[]; fields: (keyof T)[]; onChange: (items: T[]) => void; create: () => T }) { return <div><div className="mb-2 flex items-center justify-between"><Label text={label} /><Button type="button" size="sm" variant="outline" onClick={() => onChange([...items, create()])}><Plus size={13} />Add</Button></div>{items.map((item, index) => <div key={index} className="mb-2 flex gap-2 overflow-x-auto">{fields.map((field) => <input key={String(field)} aria-label={`${label} ${String(field)}`} value={item[field]} placeholder={String(field)} onChange={(event) => { const next = structuredClone(items); next[index][field] = event.target.value as T[keyof T]; onChange(next); }} className={`${inputClass} min-w-32`} />)}<button type="button" aria-label={`Remove ${label.toLowerCase()} item`} onClick={() => onChange(items.filter((_, itemIndex) => itemIndex !== index))} className="text-rose-300"><Trash2 size={14} /></button></div>)}</div>; }
function FigureEditor({ value, onChange }: { value: FigureSpec; onChange: (value: FigureSpec) => void }) { return <div className="grid gap-3 md:grid-cols-2">{(["geometry", "x_axis", "y_axis", "group", "panel"] as const).map((key) => <Field key={key} label={key.replace("_", " ")} value={value[key]} onChange={(nextValue) => onChange({ ...value, [key]: nextValue })} />)}</div>; }

function normalizePlan(value: Record<string, unknown>): TLFPlanDraft {
  const rawOutputs = arrayValue<Record<string, unknown>>(value.outputs);
  const outputs = rawOutputs.map((item, index): TLFOutput => ({
    output_id: stringValue(item.output_id, `T-${index + 1}`), output_type: outputType(item.output_type), title: stringValue(item.title, "Untitled output"), section: stringValue(item.section, "Not specified"), purpose: stringValue(item.purpose, "Not specified"), population: stringValue(item.population, "TODO: confirm population"), population_filter: stringValue(item.population_filter, "TODO: confirm population filter"), analysis_datasets: arrayValue<string>(item.analysis_datasets), source_variables: arrayValue<SourceVariable>(item.source_variables), selection_criteria: arrayValue<string>(item.selection_criteria), treatment_variable: stringValue(item.treatment_variable, "TODO: confirm treatment variable"), analysis_method: stringValue(item.analysis_method, "TODO: confirm analysis method"), columns: arrayValue<TLFColumn>(item.columns).map((column, columnIndex) => ({ column_id: stringValue(column.column_id, `COL${columnIndex + 1}`), heading: stringValue(column.heading, "Column"), source: stringValue(column.source, "TODO: confirm source"), statistic: stringValue(column.statistic), format: stringValue(column.format, "TODO: confirm format") })), rows: arrayValue<TLFRow>(item.rows), figure: item.figure && typeof item.figure === "object" ? item.figure as FigureSpec : null, sort_order: arrayValue<string>(item.sort_order), footnotes: arrayValue<string>(item.footnotes), display_notes: arrayValue<string>(item.display_notes), programming_notes: arrayValue<string>(item.programming_notes), source_reference: stringValue(item.source_reference, "TODO: confirm SAP/protocol reference"), readiness: item.readiness === "ready" ? "ready" : "blocked", blocking_items: arrayValue<string>(item.blocking_items),
  }));
  const programs = arrayValue<TLFProgram>(value.programs).map((program) => structuredClone(program));
  for (const output of outputs) if (!programs.some((program) => program.output_id === output.output_id)) programs.push(newProgram(output.output_id));
  return { ...value, study_name: stringValue(value.study_name, "Untitled study"), analysis_standard: stringValue(value.analysis_standard, "ADaM metadata supplied by user"), outputs, programs, assumptions: arrayValue<string>(value.assumptions), unresolved_items: arrayValue<string>(value.unresolved_items) } as TLFPlanDraft;
}
function newOutput(id: string): TLFOutput { return { output_id: id, output_type: "table", title: "New output", section: "Not specified", purpose: "Not specified", population: "TODO: confirm population", population_filter: "TODO: confirm population filter", analysis_datasets: [], source_variables: [], selection_criteria: [], treatment_variable: "TODO: confirm treatment variable", analysis_method: "TODO: confirm analysis method", columns: [], rows: [], figure: null, sort_order: [], footnotes: [], display_notes: [], programming_notes: [], source_reference: "TODO: confirm SAP/protocol reference", readiness: "blocked", blocking_items: ["Complete the new output specification."] }; }
function newProgram(outputId: string): TLFProgram { return { output_id: outputId, input_datasets: [], derivation_steps: [], r_code: "# TODO: implement reviewed output logic", sas_code: "/* TODO: implement reviewed output logic */", review_notes: ["Statistical-programming review required"] }; }
function newFigure(): FigureSpec { return { geometry: "TODO: confirm figure type", x_axis: "TODO: confirm x-axis", y_axis: "TODO: confirm y-axis", group: "", panel: "" }; }
function uniqueId(outputs: TLFOutput[], base: string): string { const known = new Set(outputs.map((item) => item.output_id.toLowerCase())); let candidate = base; let suffix = 2; while (known.has(candidate.toLowerCase())) candidate = `${base}-${suffix++}`; return candidate; }
function splitComma(value: string): string[] { return value.split(",").map((item) => item.trim()).filter(Boolean); }
function splitLines(value: string): string[] { return value.split("\n").map((item) => item.trim()).filter(Boolean); }
function arrayValue<T>(value: unknown): T[] { return Array.isArray(value) ? value as T[] : []; }
function stringValue(value: unknown, fallback = ""): string { return typeof value === "string" ? value : fallback; }
function outputType(value: unknown): OutputType { return value === "listing" || value === "figure" ? value : "table"; }
