"use client";

import { useEffect, useMemo, useState } from "react";
import { ArrowDown, ArrowUp, Copy, Plus, Save, Trash2 } from "lucide-react";
import { Button } from "./ui/button";

type OutputType = "table" | "listing" | "figure";
type OutputBasis = "source_supported" | "conventional_proposal";
type ReviewStage = "inventory" | "analysis" | "programming";
interface TLFColumn { column_id: string; heading: string; source: string; statistic: string; format: string; }
interface TLFRow { row_id: string; label: string; source: string; statistic: string; condition: string; format: string; }
interface SourceVariable { dataset: string; variable: string; role: string; derivation: string; }
interface FigureSpec { geometry: string; x_axis: string; y_axis: string; group: string; panel: string; }
interface TLFOutput {
  output_id: string; output_type: OutputType; title: string; basis: OutputBasis; section: string; purpose: string;
  population: string; population_filter: string; analysis_datasets: string[]; source_variables: SourceVariable[];
  selection_criteria: string[]; treatment_variable: string; analysis_method: string; columns: TLFColumn[];
  rows: TLFRow[]; figure: FigureSpec | null; sort_order: string[]; footnotes: string[]; display_notes: string[];
  programming_notes: string[]; source_reference: string; readiness: "ready" | "blocked"; blocking_items: string[];
}
interface TLFProgram { output_id: string; input_datasets: string[]; adam_sources: SourceVariable[]; derivation_steps: string[]; r_code: string; sas_code: string; review_notes: string[]; }
export interface TLFPlanDraft extends Record<string, unknown> {
  study_name: string; analysis_standard: string; outputs: TLFOutput[]; programs: TLFProgram[];
  assumptions: string[]; unresolved_items: string[];
}
export interface TLFAnalysisPlanDraft extends Record<string, unknown> {
  study_name: string; analysis_standard: string; outputs: TLFOutput[];
  assumptions: string[]; unresolved_items: string[];
}
export interface TLFInventoryPlanDraft extends Record<string, unknown> {
  study_name: string; analysis_standard: string;
  outputs: Array<Pick<TLFOutput, "output_id" | "output_type" | "title" | "basis" | "section" | "purpose" | "population" | "source_reference">>;
  assumptions: string[]; unresolved_items: string[];
}

const inputClass = "focus-ring h-9 w-full rounded-md border border-white/15 bg-[#111113] px-2.5 text-xs text-zinc-200";
const areaClass = "focus-ring min-h-20 w-full rounded-md border border-white/15 bg-[#111113] px-2.5 py-2 text-xs leading-5 text-zinc-200";

export function TLFInventoryReview({ value, onChange, onApprove, saving, error }: {
  value: Record<string, unknown>; onChange: (value: TLFInventoryPlanDraft) => void; onApprove: (value: TLFInventoryPlanDraft) => void; saving: boolean; error?: string;
}) {
  const [view, setView] = useState<"preview" | "inventory" | "json">("preview");
  return <div className="space-y-5">
    <div className="rounded-xl border border-violet-500/20 bg-violet-500/[0.06] p-4">
      <p className="text-xs font-black uppercase tracking-[0.14em] text-violet-300">Output table of contents review required</p>
      <p className="mt-1 text-sm text-zinc-300">Confirm the planned tables, listings, and figures before detailed shells are generated.</p>
    </div>
    <div className="flex flex-wrap gap-2 border-b border-white/10" role="tablist" aria-label="TLF inventory review views">
      {([['preview', 'Table of contents'], ['inventory', 'Edit outputs'], ['json', 'Advanced JSON']] as const).map(([key, label]) => <button key={key} type="button" role="tab" aria-selected={view === key} onClick={() => setView(key)} className={`focus-ring rounded-t-lg px-4 py-2.5 text-sm font-bold ${view === key ? "border-b-2 border-violet-500 text-violet-300" : "text-zinc-500 hover:text-zinc-300"}`}>{label}</button>)}
    </div>
    {view === "preview" && <TLFTableOfContents value={value} onEdit={() => setView("inventory")} editLabel="Edit outputs" showReadiness={false} />}
    {view === "inventory" && <TLFReviewEditor value={value} onChange={(next) => onChange(toInventoryPlan(next))} onSave={() => undefined} saving={saving} error={error} approvalStage="inventory" onApproveStage={(next) => onApprove(toInventoryPlan(next))} hideIntro />}
    {view === "json" && <TLFJsonEditor value={value} onApply={(next) => { onChange(toInventoryPlan(normalizePlan(next))); setView("inventory"); }} />}
  </div>;
}

export function TLFShellReview({ value, onChange, onApprove, saving, error }: {
  value: Record<string, unknown>; onChange: (value: TLFAnalysisPlanDraft) => void; onApprove: (value: TLFAnalysisPlanDraft) => void; saving: boolean; error?: string;
}) {
  const [view, setView] = useState<"preview" | "shell" | "json">("preview");
  return <div className="space-y-5">
    <div className="rounded-xl border border-violet-500/20 bg-violet-500/[0.06] p-4">
      <p className="text-xs font-black uppercase tracking-[0.14em] text-violet-300">TLF shell review required</p>
      <p className="mt-1 text-sm text-zinc-300">Review the output index, then use the guided Shell editor to make changes. Programming will not start until you approve the shell.</p>
    </div>
    <div className="flex flex-wrap gap-2 border-b border-white/10" role="tablist" aria-label="TLF shell review views">
      {([['preview', 'Preview'], ['shell', 'Shell'], ['json', 'Advanced JSON']] as const).map(([key, label]) => <button key={key} type="button" role="tab" aria-selected={view === key} onClick={() => setView(key)} className={`focus-ring rounded-t-lg px-4 py-2.5 text-sm font-bold ${view === key ? "border-b-2 border-violet-500 text-violet-300" : "text-zinc-500 hover:text-zinc-300"}`}>{label}</button>)}
    </div>
    {view === "preview" && <TLFTableOfContents value={value} onEdit={() => setView("shell")} />}
    {view === "shell" && <TLFReviewEditor value={value} onChange={(next) => onChange(toAnalysisPlan(next))} onSave={() => undefined} saving={saving} error={error} approvalStage="analysis" onApproveStage={(next) => onApprove(toAnalysisPlan(next))} hideIntro />}
    {view === "json" && <TLFJsonEditor value={value} onApply={(next) => { onChange(toAnalysisPlan(normalizePlan(next))); setView("shell"); }} />}
  </div>;
}

export function TLFProgrammingReview({ value, onChange, onApprove, saving, error }: {
  value: Record<string, unknown>; onChange: (value: TLFPlanDraft) => void; onApprove: (value: TLFPlanDraft) => void; saving: boolean; error?: string;
}) {
  return <div className="space-y-5">
    <div className="rounded-xl border border-violet-500/20 bg-violet-500/[0.06] p-4">
      <p className="text-xs font-black uppercase tracking-[0.14em] text-violet-300">ADaM-linked programming review required</p>
      <p className="mt-1 text-sm text-zinc-300">Review each output&apos;s ADaM dataset-variable links, derivation steps, and non-executed R/SAS scaffolds before final artifacts are rendered.</p>
    </div>
    <TLFReviewEditor value={value} onChange={onChange} onSave={() => undefined} saving={saving} error={error} approvalStage="programming" onApproveStage={onApprove} hideIntro />
  </div>;
}

export function TLFReviewEditor({ value, onChange, onSave, saving, error, approvalStage, onApproveStage, hideIntro = false }: {
  value: Record<string, unknown>; onChange: (value: TLFPlanDraft) => void; onSave: (value: TLFPlanDraft) => void; saving: boolean; error?: string; approvalStage?: ReviewStage; onApproveStage?: (value: TLFPlanDraft) => void; hideIntro?: boolean;
}) {
  const plan = useMemo(() => normalizePlan(value), [value]);
  const [selected, setSelected] = useState(plan.outputs[0]?.output_id ?? "");
  const [filter, setFilter] = useState<"all" | OutputType>("all");
  const [stage, setStage] = useState<ReviewStage>(approvalStage ?? "inventory");
  const activeIndex = Math.max(0, plan.outputs.findIndex((item) => item.output_id === selected));
  const active = plan.outputs[activeIndex];
  const filtered = plan.outputs.filter((item) => filter === "all" || item.output_type === filter);
  const approvalIssues = approvalStage === "inventory" ? inventoryIssues(plan) : approvalStage === "analysis" ? shellIssues(plan) : approvalStage === "programming" ? programmingIssues(plan) : [];

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
    {!hideIntro && <div className="rounded-xl border border-violet-500/20 bg-violet-500/[0.06] p-4">
      <p className="text-xs font-black uppercase tracking-[0.14em] text-violet-300">{approvalStage ? "TLF staged review required" : "TLF review workspace"}</p>
      <p className="mt-1 text-sm text-zinc-300">{approvalStage ? "Review and approve this stage before the pipeline can continue." : "Review source-grounded outputs, analysis metadata, display rules, and non-executed program scaffolds. Saving revalidates the full plan and rebuilds every artifact."}</p>
    </div>}
    <div className="flex flex-wrap gap-2 border-b border-white/10" role="tablist" aria-label="TLF review stages">
      {([
        ["inventory", "1 · Output inventory"],
        ["analysis", "2 · Analysis & display"],
        ["programming", "3 · Programming augmentation"],
      ] as const).filter(([value]) => !approvalStage || value === approvalStage).map(([value, label]) => <button key={value} type="button" role="tab" aria-selected={stage === value} onClick={() => setStage(value)} className={`focus-ring rounded-t-lg px-4 py-2.5 text-sm font-bold ${stage === value ? "border-b-2 border-violet-500 text-violet-300" : "text-zinc-500 hover:text-zinc-300"}`}>{label}</button>)}
    </div>
    <div className="grid gap-5 xl:grid-cols-[260px_minmax(0,1fr)]">
      <aside className="space-y-3 rounded-xl border border-white/10 bg-white/[0.02] p-3">
        <div className="flex gap-2"><select aria-label="Filter outputs" value={filter} onChange={(event) => setFilter(event.target.value as typeof filter)} className={inputClass}><option value="all">All outputs</option><option value="table">Tables</option><option value="listing">Listings</option><option value="figure">Figures</option></select>{(!approvalStage || approvalStage === "inventory") && <Button type="button" size="sm" variant="outline" onClick={addOutput}><Plus size={14} /></Button>}</div>
        <div className="space-y-2">{filtered.map((item) => <button type="button" key={item.output_id} onClick={() => setSelected(item.output_id)} className={`w-full rounded-lg border p-3 text-left ${selected === item.output_id ? "border-violet-500/50 bg-violet-500/10" : "border-white/10 bg-black/10"}`}><div className="flex items-center justify-between gap-2"><span className="font-mono text-xs font-black text-zinc-100">{item.output_id}</span><span className={`rounded-full px-2 py-0.5 text-[9px] font-black uppercase ${item.readiness === "ready" ? "bg-emerald-500/15 text-emerald-300" : "bg-amber-500/15 text-amber-300"}`}>{item.readiness}</span></div><p className="mt-1 line-clamp-2 text-xs text-zinc-400">{item.title}</p><p className={`mt-2 text-[9px] font-black uppercase tracking-wider ${item.basis === "source_supported" ? "text-sky-300" : "text-amber-300"}`}>{basisLabel(item.basis)}</p></button>)}</div>
      </aside>
      {active ? <main className="space-y-5">
        {stage === "inventory" && <>
          <div className="flex flex-wrap items-center justify-between gap-2"><div className="flex gap-2"><Button type="button" size="sm" variant="outline" onClick={() => move(-1)}><ArrowUp size={14} /></Button><Button type="button" size="sm" variant="outline" onClick={() => move(1)}><ArrowDown size={14} /></Button><Button type="button" size="sm" variant="outline" onClick={duplicate}><Copy size={14} />Duplicate</Button></div><Button type="button" size="sm" variant="danger" onClick={remove}><Trash2 size={14} />Remove</Button></div>
          <Section title="Output overview"><div className="grid gap-3 md:grid-cols-4"><Field label="Output ID" value={active.output_id} onChange={(value) => updateOutput("output_id", value)} /><label><Label text="Type" /><select value={active.output_type} onChange={(event) => updateOutput("output_type", event.target.value)} className={inputClass}><option value="table">Table</option><option value="listing">Listing</option><option value="figure">Figure</option></select></label><label><Label text="Basis" /><select value={active.basis} onChange={(event) => updateOutput("basis", event.target.value)} className={inputClass}><option value="source_supported">Source-defined</option><option value="conventional_proposal">Conventional proposal</option></select></label><Field label="Section" value={active.section} onChange={(value) => updateOutput("section", value)} /></div><Field label="Title" value={active.title} onChange={(value) => updateOutput("title", value)} /><Text label="Purpose" value={active.purpose} onChange={(value) => updateOutput("purpose", value)} /><Field label="SAP / protocol reference" value={active.source_reference} onChange={(value) => updateOutput("source_reference", value)} /></Section>
        </>}
        {stage === "analysis" && <>
          <Section title="Shell preview"><ShellPreview output={active} /></Section>
          <Section title="Population and analysis"><div className="grid gap-3 md:grid-cols-2"><Field label="Population" value={active.population} onChange={(value) => updateOutput("population", value)} /><Field label="Population filter" value={active.population_filter} onChange={(value) => updateOutput("population_filter", value)} /><Field label="Treatment variable" value={active.treatment_variable} onChange={(value) => updateOutput("treatment_variable", value)} /><Field label="Analysis datasets (comma-separated)" value={active.analysis_datasets.join(", ")} onChange={(value) => updateOutput("analysis_datasets", splitComma(value))} /></div><Text label="Analysis method" value={active.analysis_method} onChange={(value) => updateOutput("analysis_method", value)} /><Text label="Selection criteria (one per line)" value={active.selection_criteria.join("\n")} onChange={(value) => updateOutput("selection_criteria", splitLines(value))} /><SourceVariables value={active.source_variables} onChange={(value) => updateOutput("source_variables", value)} /></Section>
          <Section title="Display specification">{active.output_type === "figure" ? <FigureEditor value={active.figure ?? newFigure()} onChange={(value) => updateOutput("figure", value)} /> : <DisplayGrid type={active.output_type} columns={active.columns} rows={active.rows} onColumns={(value) => updateOutput("columns", value)} onRows={(value) => updateOutput("rows", value)} />}<Text label="Sort order (one per line)" value={active.sort_order.join("\n")} onChange={(value) => updateOutput("sort_order", splitLines(value))} /><Text label="Footnotes (one per line)" value={active.footnotes.join("\n")} onChange={(value) => updateOutput("footnotes", splitLines(value))} /></Section>
        </>}
        {stage === "programming" && <Section title="Programming scaffolds"><p className="rounded-lg border border-blue-500/20 bg-blue-500/10 px-3 py-2 text-xs leading-5 text-blue-200">ADaM schema links must match the dataset-variable sources approved in the shell. Generated code is reviewable scaffolding and is never executed.</p><Field label="Input datasets (comma-separated)" value={(program?.input_datasets ?? []).join(", ")} onChange={(value) => updateProgram("input_datasets", splitComma(value))} /><SourceVariables label="ADaM schema links" value={program?.adam_sources ?? []} onChange={(value) => updateProgram("adam_sources", value)} /><Text label="Derivation steps (one per line)" value={(program?.derivation_steps ?? []).join("\n")} onChange={(value) => updateProgram("derivation_steps", splitLines(value))} /><Text label="R scaffold" value={program?.r_code ?? ""} onChange={(value) => updateProgram("r_code", value)} mono /><Text label="SAS scaffold" value={program?.sas_code ?? ""} onChange={(value) => updateProgram("sas_code", value)} mono /></Section>}
        <Section title="Readiness blockers"><Text label="Blocking items (one per line)" value={active.blocking_items.join("\n")} onChange={(value) => updateOutput("blocking_items", splitLines(value))} />{active.readiness === "blocked" && <p className="text-xs text-amber-300">This output remains in the package but is marked blocked until its TODOs and blocking items are resolved.</p>}</Section>
      </main> : <div className="grid min-h-64 place-items-center rounded-xl border border-dashed border-white/15 text-sm text-zinc-500">Add an output to begin review.</div>}
    </div>
    {approvalIssues.length > 0 && <ul className="space-y-1 rounded-lg border border-amber-500/20 bg-amber-500/10 p-3 text-sm text-amber-200">{approvalIssues.map((issue) => <li key={issue}>{issue}</li>)}</ul>}
    {error && <div className="rounded-lg border border-rose-500/20 bg-rose-500/10 p-3 text-sm text-rose-300">{error}</div>}
    {approvalStage ? <Button variant="clinical" onClick={() => onApproveStage?.(plan)} disabled={saving || !plan.outputs.length || approvalIssues.length > 0}><Save size={16} />{saving ? "Approving stage…" : approvalStage === "inventory" ? "Approve table of contents and generate shells" : approvalStage === "analysis" ? "Approve shells and generate programming" : "Approve programming and render artifacts"}</Button> : <Button variant="clinical" onClick={() => onSave(plan)} disabled={saving || !plan.outputs.length}><Save size={16} />{saving ? "Validating and rebuilding…" : "Save review and rebuild artifacts"}</Button>}
  </div>;
}

export function TLFTableOfContents({ value, onEdit, editLabel = "Edit shells", showReadiness = true }: { value: Record<string, unknown>; onEdit?: () => void; editLabel?: string; showReadiness?: boolean }) {
  const plan = useMemo(() => normalizePlan(value), [value]);
  const counts: Record<OutputType, number> = { table: 0, listing: 0, figure: 0 };
  plan.outputs.forEach((output) => { counts[output.output_type] += 1; });
  return <div className="space-y-5">
    <div className="flex flex-wrap items-start justify-between gap-4 rounded-xl border border-white/10 bg-white/[0.02] p-5">
      <div><p className="text-[10px] font-black uppercase tracking-[0.14em] text-zinc-500">TLF package</p><h3 className="mt-1 text-lg font-black text-zinc-100">{plan.study_name}</h3><p className="mt-1 text-sm text-zinc-400">{plan.analysis_standard}</p></div>
      <div className="flex gap-2">{([['table', counts.table], ['listing', counts.listing], ['figure', counts.figure]] as const).map(([type, count]) => <div key={type} className="min-w-20 rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-center"><p className="text-lg font-black text-zinc-100">{count}</p><p className="text-[9px] font-black uppercase tracking-wider text-zinc-500">{type}{count === 1 ? '' : 's'}</p></div>)}</div>
    </div>
    <section className="overflow-hidden rounded-xl border border-white/10 bg-white/[0.02]">
      <div className="flex items-center justify-between gap-3 border-b border-white/10 px-4 py-3"><div><h3 className="text-sm font-black text-zinc-100">Table of contents</h3><p className="mt-0.5 text-xs text-zinc-500">The ordered list of planned tables, listings, and figures.</p></div>{onEdit && <Button type="button" size="sm" variant="outline" onClick={onEdit}>{editLabel}</Button>}</div>
      {plan.outputs.length ? <div className="overflow-x-auto"><table className="min-w-full border-collapse text-left text-sm"><thead className="bg-white/[0.035] text-[10px] font-black uppercase tracking-wider text-zinc-500"><tr><th className="px-4 py-2.5">No.</th><th className="px-4 py-2.5">Output</th><th className="px-4 py-2.5">Title</th><th className="px-4 py-2.5">Basis</th><th className="px-4 py-2.5">Section</th><th className="px-4 py-2.5">Population</th>{showReadiness && <th className="px-4 py-2.5">Status</th>}</tr></thead><tbody>{plan.outputs.map((output, index) => <tr key={`${output.output_id}-${index}`} className="border-t border-white/[0.07]"><td className="px-4 py-3 font-mono text-xs text-zinc-600">{String(index + 1).padStart(2, '0')}</td><td className="px-4 py-3"><span className="font-mono text-xs font-black text-violet-300">{output.output_id}</span><span className="ml-2 rounded bg-white/[0.06] px-1.5 py-0.5 text-[9px] font-black uppercase text-zinc-400">{output.output_type}</span></td><td className="max-w-md px-4 py-3 font-semibold text-zinc-200">{output.title}</td><td className="px-4 py-3"><span className={`whitespace-nowrap rounded-full px-2 py-1 text-[9px] font-black uppercase ${output.basis === "source_supported" ? "bg-sky-500/15 text-sky-300" : "bg-amber-500/15 text-amber-300"}`}>{basisLabel(output.basis)}</span></td><td className="px-4 py-3 text-xs text-zinc-400">{output.section}</td><td className="px-4 py-3 text-xs text-zinc-400">{output.population}</td>{showReadiness && <td className="px-4 py-3"><span className={`rounded-full px-2 py-1 text-[9px] font-black uppercase ${output.readiness === 'ready' ? 'bg-emerald-500/15 text-emerald-300' : 'bg-amber-500/15 text-amber-300'}`}>{output.readiness}</span></td>}</tr>)}</tbody></table></div> : <p className="p-8 text-center text-sm text-zinc-500">No outputs have been defined.</p>}
    </section>
    {(plan.assumptions.length > 0 || plan.unresolved_items.length > 0) && <div className="grid gap-4 md:grid-cols-2">{plan.assumptions.length > 0 && <SummaryList title="Assumptions" items={plan.assumptions} />}{plan.unresolved_items.length > 0 && <SummaryList title="Items requiring confirmation" items={plan.unresolved_items} warning />}</div>}
  </div>;
}

export function TLFJsonEditor({ value, onApply, onSave, saving = false, error }: { value: Record<string, unknown>; onApply?: (value: Record<string, unknown>) => void; onSave?: (value: Record<string, unknown>) => void; saving?: boolean; error?: string }) {
  const [draft, setDraft] = useState(() => JSON.stringify(value, null, 2));
  const [parseError, setParseError] = useState<string | null>(null);
  useEffect(() => setDraft(JSON.stringify(value, null, 2)), [value]);
  const submit = () => {
    try {
      const parsed: unknown = JSON.parse(draft);
      if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") throw new Error("The TLF shell must be a JSON object.");
      setParseError(null);
      (onSave ?? onApply)?.(parsed as Record<string, unknown>);
    } catch (caught) { setParseError(caught instanceof Error ? caught.message : "Enter valid JSON."); }
  };
  return <div className="space-y-4">
    <div className="rounded-lg border border-amber-500/20 bg-amber-500/[0.07] px-4 py-3 text-sm leading-6 text-amber-100"><strong>Advanced editor.</strong> This view is intended for technical reviewers. Most users should make changes in the Shell tab.</div>
    <textarea aria-label="Advanced TLF JSON" value={draft} onChange={(event) => setDraft(event.target.value)} spellCheck={false} className="focus-ring min-h-[32rem] w-full rounded-xl border border-white/15 bg-[#0d0d0f] p-4 font-mono text-xs leading-5 text-zinc-200" />
    {(parseError || error) && <div className="rounded-lg border border-rose-500/20 bg-rose-500/10 p-3 text-sm text-rose-300">{parseError ?? error}</div>}
    <Button type="button" variant="clinical" onClick={submit} disabled={saving}><Save size={16} />{saving ? "Validating and rebuilding…" : onSave ? "Save JSON and rebuild artifacts" : "Apply JSON to shell"}</Button>
  </div>;
}

function SummaryList({ title, items, warning = false }: { title: string; items: string[]; warning?: boolean }) { return <section className={`rounded-xl border p-4 ${warning ? 'border-amber-500/20 bg-amber-500/[0.06]' : 'border-white/10 bg-white/[0.02]'}`}><h3 className="text-sm font-black text-zinc-100">{title}</h3><ul className="mt-2 space-y-1 text-xs leading-5 text-zinc-400">{items.map((item, index) => <li key={`${item}-${index}`}>• {item}</li>)}</ul></section>; }

function Section({ title, children }: { title: string; children: React.ReactNode }) { return <section className="space-y-3 rounded-xl border border-white/10 bg-white/[0.02] p-4"><h3 className="text-sm font-black text-zinc-100">{title}</h3>{children}</section>; }
function Label({ text }: { text: string }) { return <span className="mb-1.5 block text-[10px] font-black uppercase tracking-wider text-zinc-500">{text}</span>; }
function Field({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) { return <label><Label text={label} /><input value={value} onChange={(event) => onChange(event.target.value)} className={inputClass} /></label>; }
function Text({ label, value, onChange, mono = false }: { label: string; value: string; onChange: (value: string) => void; mono?: boolean }) { return <label><Label text={label} /><textarea value={value} onChange={(event) => onChange(event.target.value)} className={`${areaClass} ${mono ? "font-mono" : ""}`} /></label>; }

function SourceVariables({ value, onChange, label = "Source variables" }: { value: SourceVariable[]; onChange: (value: SourceVariable[]) => void; label?: string }) { return <div><div className="mb-2 flex items-center justify-between"><Label text={label} /><Button type="button" size="sm" variant="outline" onClick={() => onChange([...value, { dataset: "", variable: "", role: "Analysis input", derivation: "Direct" }])}><Plus size={13} />Add</Button></div>{value.map((item, index) => <div key={index} className="mb-2 grid gap-2 md:grid-cols-[1fr_1fr_1fr_1fr_32px]">{(["dataset", "variable", "role", "derivation"] as const).map((key) => <input key={key} aria-label={`${label} ${key}`} value={item[key]} placeholder={key} onChange={(event) => { const next = structuredClone(value); next[index][key] = event.target.value; onChange(next); }} className={inputClass} />)}<button type="button" aria-label={`Remove ${label.toLowerCase()} item`} onClick={() => onChange(value.filter((_, itemIndex) => itemIndex !== index))} className="text-rose-300"><Trash2 size={14} /></button></div>)}</div>; }
function DisplayGrid({ type, columns, rows, onColumns, onRows }: { type: OutputType; columns: TLFColumn[]; rows: TLFRow[]; onColumns: (value: TLFColumn[]) => void; onRows: (value: TLFRow[]) => void }) { return <div className="space-y-4"><ArrayEditor label="Columns" items={columns} fields={["column_id", "heading", "source", "statistic", "format"]} onChange={onColumns} create={() => ({ column_id: `COL${columns.length + 1}`, heading: "New column", source: "TODO: confirm source", statistic: "", format: "TODO: confirm format" })} />{type === "table" && <ArrayEditor label="Rows" items={rows} fields={["row_id", "label", "source", "statistic", "condition", "format"]} onChange={onRows} create={() => ({ row_id: `ROW${rows.length + 1}`, label: "New row", source: "TODO: confirm source", statistic: "", condition: "", format: "TODO: confirm format" })} />}</div>; }
function ArrayEditor<T extends Record<string, string>>({ label, items, fields, onChange, create }: { label: string; items: T[]; fields: (keyof T)[]; onChange: (items: T[]) => void; create: () => T }) { return <div><div className="mb-2 flex items-center justify-between"><Label text={label} /><Button type="button" size="sm" variant="outline" onClick={() => onChange([...items, create()])}><Plus size={13} />Add</Button></div>{items.map((item, index) => <div key={index} className="mb-2 flex gap-2 overflow-x-auto">{fields.map((field) => <input key={String(field)} aria-label={`${label} ${String(field)}`} value={item[field]} placeholder={String(field)} onChange={(event) => { const next = structuredClone(items); next[index][field] = event.target.value as T[keyof T]; onChange(next); }} className={`${inputClass} min-w-32`} />)}<button type="button" aria-label={`Remove ${label.toLowerCase()} item`} onClick={() => onChange(items.filter((_, itemIndex) => itemIndex !== index))} className="text-rose-300"><Trash2 size={14} /></button></div>)}</div>; }
function FigureEditor({ value, onChange }: { value: FigureSpec; onChange: (value: FigureSpec) => void }) { return <div className="grid gap-3 md:grid-cols-2">{(["geometry", "x_axis", "y_axis", "group", "panel"] as const).map((key) => <Field key={key} label={key.replace("_", " ")} value={value[key]} onChange={(nextValue) => onChange({ ...value, [key]: nextValue })} />)}</div>; }
function ShellPreview({ output }: { output: TLFOutput }) {
  if (output.output_type === "figure") return <FigureShell output={output} />;
  if (output.output_type === "listing") return <ListingShell output={output} />;
  return <SummaryTableShell output={output} />;
}

function SummaryTableShell({ output }: { output: TLFOutput }) {
  return <div className="overflow-hidden rounded-lg border border-zinc-300 bg-white text-zinc-950 shadow-sm" aria-label="Summary table shell">
    <div className="border-b-2 border-zinc-900 px-5 py-4 text-center">
      <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-zinc-500">{output.output_id} · Summary table shell</p>
      <h4 className="mt-1 text-sm font-bold leading-5">{output.title}</h4>
      <p className="mt-1 text-[11px] text-zinc-600">{output.population}</p>
    </div>
    {output.columns.length > 0 && output.rows.length > 0 ? <div className="overflow-x-auto px-4 py-3">
      <table className="min-w-full border-collapse text-[11px]">
        <thead>
          <tr className="border-b border-zinc-900 align-bottom">
            <th className="min-w-52 px-2 py-2 text-left font-semibold">Parameter / Statistic</th>
            {output.columns.map((column) => <th key={column.column_id} className="min-w-32 px-3 py-2 text-center font-semibold"><span className="block whitespace-pre-line">{column.heading}</span><span className="mt-0.5 block font-normal text-zinc-500">(N=XX)</span></th>)}
          </tr>
        </thead>
        <tbody>{output.rows.map((row, index) => <tr key={row.row_id} className={`${index === 0 ? "" : "border-t border-zinc-200"} align-top`}>
          <td className="px-2 py-2.5"><span className="block font-medium">{row.label}</span>{row.condition && <span className="mt-0.5 block text-[9px] leading-4 text-zinc-500">{row.condition}</span>}</td>
          {output.columns.map((column) => <td key={column.column_id} className="px-3 py-2.5 text-center font-mono text-zinc-700">{summaryPlaceholder(row.statistic || column.statistic, row.format || column.format)}</td>)}
        </tr>)}</tbody>
      </table>
    </div> : <p className="p-8 text-center text-xs text-amber-700">Add at least one display column and one summary row to build the table shell.</p>}
    <div className="space-y-1 border-t border-zinc-300 px-5 py-3 text-[9px] leading-4 text-zinc-600">
      {output.footnotes.length > 0 ? output.footnotes.map((footnote, index) => <p key={`${footnote}-${index}`}>{footnoteLabel(index)} {footnote}</p>) : <p>Note: Add footnotes in the display specification.</p>}
      <p>Population: {output.population_filter}</p>
      <p>Source: {output.source_reference}</p>
    </div>
  </div>;
}

function ListingShell({ output }: { output: TLFOutput }) {
  return <div className="overflow-hidden rounded-lg border border-zinc-300 bg-white text-zinc-950 shadow-sm" aria-label="Listing shell">
    <div className="border-b-2 border-zinc-900 px-5 py-4 text-center"><p className="font-mono text-[10px] font-bold uppercase tracking-wider text-zinc-500">{output.output_id} · Listing shell</p><h4 className="mt-1 text-sm font-bold">{output.title}</h4><p className="mt-1 text-[11px] text-zinc-600">{output.population}</p></div>
    {output.columns.length > 0 ? <div className="overflow-x-auto px-4 py-3"><table className="min-w-full border-collapse text-[10px]"><thead><tr className="border-b border-zinc-900">{output.columns.map((column) => <th key={column.column_id} className="min-w-28 px-2 py-2 text-left font-semibold">{column.heading}</th>)}</tr></thead><tbody>{[0, 1, 2].map((rowIndex) => <tr key={rowIndex} className="border-t border-zinc-200">{output.columns.map((column) => <td key={column.column_id} className="px-2 py-2 font-mono text-zinc-500">&lt;{shortSource(column.source)}&gt;</td>)}</tr>)}</tbody></table></div> : <p className="p-8 text-center text-xs text-amber-700">Add display columns to build the listing shell.</p>}
    <div className="border-t border-zinc-300 px-5 py-3 text-[9px] text-zinc-600">Source: {output.source_reference}</div>
  </div>;
}

function FigureShell({ output }: { output: TLFOutput }) { const figure = output.figure; return <div className="rounded-lg border border-zinc-300 bg-white p-5 text-zinc-950 shadow-sm" aria-label="Figure shell"><div className="text-center"><p className="font-mono text-[10px] font-bold uppercase tracking-wider text-zinc-500">{output.output_id} · Figure shell</p><h4 className="mt-1 text-sm font-bold">{output.title}</h4><p className="mt-1 text-[11px] text-zinc-600">{output.population}</p></div><div className="mt-5 grid min-h-56 place-items-center border border-dashed border-zinc-400 bg-zinc-50 p-6 text-center"><div><p className="text-xs font-bold">{figure?.geometry || "Figure placeholder"}</p><p className="mt-3 text-[10px] text-zinc-500">Y: {figure?.y_axis || "Not specified"}</p><div className="mx-auto my-3 h-24 w-48 border-b border-l border-zinc-500" /><p className="text-[10px] text-zinc-500">X: {figure?.x_axis || "Not specified"}{figure?.group ? ` · Group: ${figure.group}` : ""}</p></div></div><p className="mt-3 text-[9px] text-zinc-600">Source: {output.source_reference}</p></div>; }

function summaryPlaceholder(statistic: string, format: string): string {
  const value = `${statistic} ${format}`.toLowerCase();
  if (value.includes("n (%)") || value.includes("count") || value.includes("percent")) return "XX (XX.X)";
  if (value.includes("confidence") || value.includes("95% ci") || value.includes("ci")) return "(XX.X, XX.X)";
  if (value.includes("p-value") || value.includes("p value")) return "0.XXXX";
  if (value.includes("mean") && value.includes("sd")) return "XX.X (XX.XX)";
  if (value.includes("median") || value.includes("mean") || value.includes("ls mean")) return "XX.X";
  if (value.includes("min") && value.includes("max")) return "XX.X, XX.X";
  return "XX.X";
}
function footnoteLabel(index: number): string { return `${String.fromCharCode(97 + (index % 26))}.`; }
function shortSource(source: string): string { const value = source.trim(); return value.length > 18 ? `${value.slice(0, 15)}…` : value || "value"; }

function normalizePlan(value: Record<string, unknown>): TLFPlanDraft {
  const rawOutputs = arrayValue<Record<string, unknown>>(value.outputs);
  const outputs = rawOutputs.map((item, index): TLFOutput => ({
    output_id: stringValue(item.output_id, `T-${index + 1}`), output_type: outputType(item.output_type), title: stringValue(item.title, "Untitled output"), basis: outputBasis(item.basis), section: stringValue(item.section, "Not specified"), purpose: stringValue(item.purpose, "Not specified"), population: stringValue(item.population, "TODO: confirm population"), population_filter: stringValue(item.population_filter, "TODO: confirm population filter"), analysis_datasets: arrayValue<string>(item.analysis_datasets), source_variables: arrayValue<SourceVariable>(item.source_variables), selection_criteria: arrayValue<string>(item.selection_criteria), treatment_variable: stringValue(item.treatment_variable, "TODO: confirm treatment variable"), analysis_method: stringValue(item.analysis_method, "TODO: confirm analysis method"), columns: arrayValue<TLFColumn>(item.columns).map((column, columnIndex) => ({ column_id: stringValue(column.column_id, `COL${columnIndex + 1}`), heading: stringValue(column.heading, "Column"), source: stringValue(column.source, "TODO: confirm source"), statistic: stringValue(column.statistic), format: stringValue(column.format, "TODO: confirm format") })), rows: arrayValue<TLFRow>(item.rows), figure: item.figure && typeof item.figure === "object" ? item.figure as FigureSpec : null, sort_order: arrayValue<string>(item.sort_order), footnotes: arrayValue<string>(item.footnotes), display_notes: arrayValue<string>(item.display_notes), programming_notes: arrayValue<string>(item.programming_notes), source_reference: stringValue(item.source_reference, "TODO: confirm SAP/protocol reference"), readiness: item.readiness === "ready" ? "ready" : "blocked", blocking_items: arrayValue<string>(item.blocking_items),
  }));
  const programs = arrayValue<Record<string, unknown>>(value.programs).map((program): TLFProgram => ({
    output_id: stringValue(program.output_id),
    input_datasets: arrayValue<string>(program.input_datasets),
    adam_sources: arrayValue<SourceVariable>(program.adam_sources).map((source) => ({
      dataset: stringValue(source.dataset),
      variable: stringValue(source.variable),
      role: stringValue(source.role, "Analysis input"),
      derivation: stringValue(source.derivation, "Direct"),
    })),
    derivation_steps: arrayValue<string>(program.derivation_steps),
    r_code: stringValue(program.r_code, "# TODO: implement reviewed output logic"),
    sas_code: stringValue(program.sas_code, "/* TODO: implement reviewed output logic */"),
    review_notes: arrayValue<string>(program.review_notes),
  }));
  for (const output of outputs) if (!programs.some((program) => program.output_id === output.output_id)) programs.push(newProgram(output.output_id));
  return { ...value, study_name: stringValue(value.study_name, "Untitled study"), analysis_standard: stringValue(value.analysis_standard, "ADaM metadata supplied by user"), outputs, programs, assumptions: arrayValue<string>(value.assumptions), unresolved_items: arrayValue<string>(value.unresolved_items) } as TLFPlanDraft;
}
function newOutput(id: string): TLFOutput { return { output_id: id, output_type: "table", title: "New output", basis: "conventional_proposal", section: "Not specified", purpose: "Not specified", population: "TODO: confirm population", population_filter: "TODO: confirm population filter", analysis_datasets: [], source_variables: [], selection_criteria: [], treatment_variable: "TODO: confirm treatment variable", analysis_method: "TODO: confirm analysis method", columns: [], rows: [], figure: null, sort_order: [], footnotes: [], display_notes: [], programming_notes: [], source_reference: "CONVENTIONAL PROPOSAL — TODO: confirm SAP/protocol reference", readiness: "blocked", blocking_items: ["Complete the new output specification."] }; }
function newProgram(outputId: string): TLFProgram { return { output_id: outputId, input_datasets: [], adam_sources: [], derivation_steps: [], r_code: "# TODO: implement reviewed output logic", sas_code: "/* TODO: implement reviewed output logic */", review_notes: ["Statistical-programming review required"] }; }
function newFigure(): FigureSpec { return { geometry: "TODO: confirm figure type", x_axis: "TODO: confirm x-axis", y_axis: "TODO: confirm y-axis", group: "", panel: "" }; }
function uniqueId(outputs: TLFOutput[], base: string): string { const known = new Set(outputs.map((item) => item.output_id.toLowerCase())); let candidate = base; let suffix = 2; while (known.has(candidate.toLowerCase())) candidate = `${base}-${suffix++}`; return candidate; }
function splitComma(value: string): string[] { return value.split(",").map((item) => item.trim()).filter(Boolean); }
function splitLines(value: string): string[] { return value.split("\n").map((item) => item.trim()).filter(Boolean); }
function arrayValue<T>(value: unknown): T[] { return Array.isArray(value) ? value as T[] : []; }
function stringValue(value: unknown, fallback = ""): string { return typeof value === "string" ? value : fallback; }
function outputType(value: unknown): OutputType { return value === "listing" || value === "figure" ? value : "table"; }
function outputBasis(value: unknown): OutputBasis { return value === "conventional_proposal" ? value : "source_supported"; }
function basisLabel(value: OutputBasis): string { return value === "source_supported" ? "Source-defined" : "Conventional proposal"; }
function toInventoryPlan(plan: TLFPlanDraft): TLFInventoryPlanDraft { return { study_name: plan.study_name, analysis_standard: plan.analysis_standard, outputs: plan.outputs.map(({ output_id, output_type, title, basis, section, purpose, population, source_reference }) => ({ output_id, output_type, title, basis, section, purpose, population, source_reference })), assumptions: plan.assumptions, unresolved_items: plan.unresolved_items }; }
function toAnalysisPlan(plan: TLFPlanDraft): TLFAnalysisPlanDraft { return { study_name: plan.study_name, analysis_standard: plan.analysis_standard, outputs: plan.outputs, assumptions: plan.assumptions, unresolved_items: plan.unresolved_items }; }
function inventoryIssues(plan: TLFPlanDraft): string[] { const issues: string[] = []; const ids = new Set<string>(); plan.outputs.forEach((output) => { const id = output.output_id.trim(); if (!id) issues.push("Every output needs an identifier."); else if (ids.has(id.toLowerCase())) issues.push(`Output identifier ${id} is duplicated.`); else ids.add(id.toLowerCase()); if (!output.title.trim()) issues.push(`${id || "Unnamed output"} needs a title.`); }); return Array.from(new Set(issues)); }
function shellIssues(plan: TLFPlanDraft): string[] { const issues: string[] = []; const ids = new Set<string>(); plan.outputs.forEach((output) => { const id = output.output_id.trim(); if (!id) issues.push("Every shell needs an output identifier."); else if (ids.has(id.toLowerCase())) issues.push(`Output identifier ${id} is duplicated.`); else ids.add(id.toLowerCase()); if (!output.title.trim()) issues.push(`${id || "Unnamed output"} needs a title.`); if (output.output_type === "table" && (!output.columns.length || !output.rows.length)) issues.push(`Table ${id || "[unnamed]"} needs at least one row and one column.`); if (output.output_type === "listing" && !output.columns.length) issues.push(`Listing ${id || "[unnamed]"} needs at least one column.`); if (output.output_type === "figure" && !output.figure) issues.push(`Figure ${id || "[unnamed]"} needs a figure specification.`); }); return Array.from(new Set(issues)); }
function programmingIssues(plan: TLFPlanDraft): string[] { const issues: string[] = []; for (const output of plan.outputs) { const program = plan.programs.find((item) => item.output_id.toLowerCase() === output.output_id.toLowerCase()); if (!program) { issues.push(`${output.output_id} needs a programming scaffold.`); continue; } const inputs = new Set(program.input_datasets.map((item) => item.toLowerCase())); const expected = new Set(output.source_variables.map((source) => `${source.dataset}.${source.variable}`.toLowerCase())); const actual = new Set(program.adam_sources.map((source) => `${source.dataset}.${source.variable}`.toLowerCase())); for (const source of program.adam_sources) if (!inputs.has(source.dataset.toLowerCase())) issues.push(`${output.output_id} ADaM link ${source.dataset}.${source.variable} needs a matching input dataset.`); for (const link of expected) if (!actual.has(link)) issues.push(`${output.output_id} is missing approved ADaM schema link ${link.toUpperCase()}.`); for (const link of actual) if (!expected.has(link)) issues.push(`${output.output_id} ADaM schema link ${link.toUpperCase()} is not in the approved shell.`); } return Array.from(new Set(issues)); }
