"use client";

import { useState } from "react";
import { Activity, CheckCircle2, ChevronDown, Clock3, FileSearch, MessageSquareText, ShieldCheck, XCircle } from "lucide-react";
import type { AgentProgress } from "@/lib/types";

type AgentEvent = AgentProgress["events"][number] & { actor?: "agent" | "user" | "system" };

export function AgentTurnTimeline({ progress, compact = false }: { progress: AgentProgress; compact?: boolean }) {
  const sourceCoverage = progress.total_source_chunks
    ? Math.round((progress.read_source_chunks.length / progress.total_source_chunks) * 100)
    : 0;
  const agentEvents = progress.events.filter((event) => event.actor !== "user");
  const completed = agentEvents.filter((event) => event.ok !== false && !event.type.endsWith("rejected")).length;
  const retries = agentEvents.length - completed;
  const externalLookups = agentEvents.filter((event) => event.name && !INTERNAL_TOOLS.has(event.name)).length;

  return (
    <div className={compact ? "space-y-3" : "space-y-5"}>
      {compact ? (
        <CompactOverview
          progress={progress}
          sourceCoverage={sourceCoverage}
          completed={completed}
          retries={retries}
          externalLookups={externalLookups}
        />
      ) : <>
        <div className="rounded-xl border border-violet-500/20 bg-violet-500/[0.07] px-4 py-3 text-sm leading-6 text-violet-100">
          This execution trace shows the agent&apos;s stated purpose, approved action, safe parameters, concrete result facts, evidence references, validation findings, and timing. Uploaded source text and private model reasoning are not copied into the trace.
        </div>

        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          <AgentMetric label="Agent" value={progress.agent_id} />
          <AgentMetric label="Model" value={progress.model ?? "Not reported"} />
          <AgentMetric label="Execution status" value={humanize(progress.status)} tone={progress.status === "completed" ? "success" : "default"} />
          <AgentMetric label="Turns used" value={`${progress.turn} / ${progress.max_turns}`} />
          <AgentMetric label="Workflow stage" value={progress.stage ? `${progress.stage_index}/${progress.stage_count} · ${humanize(progress.stage)}` : "Preparing"} />
          <AgentMetric label="Elapsed trace time" value={formatElapsed(progress.started_at, progress.updated_at)} />
        </div>

        <div className="grid gap-3 lg:grid-cols-[1.4fr_1fr]">
        {progress.total_source_chunks > 0 ? (
          <section aria-label="Source review progress" className="rounded-xl border border-white/10 bg-white/[0.02] p-4">
            <div className="flex items-center justify-between gap-4 text-xs">
              <div>
                <span className="font-bold text-zinc-200">Source review</span>
                <p className="mt-1 text-zinc-500">Every available section must be reviewed before a draft can be accepted.</p>
              </div>
              <span className="font-mono text-zinc-400">{progress.read_source_chunks.length}/{progress.total_source_chunks} · {sourceCoverage}%</span>
            </div>
            <div className="mt-3 h-2 overflow-hidden rounded-full bg-white/[0.07]">
              <div className="h-full rounded-full bg-violet-500 transition-all" style={{ width: `${sourceCoverage}%` }} />
            </div>
            {progress.read_source_chunks.length > 0 && (
              <p className="mt-3 text-xs text-zinc-500">Reviewed chunk numbers: {progress.read_source_chunks.join(", ")}</p>
            )}
          </section>
        ) : <div className="rounded-xl border border-white/10 bg-white/[0.02] p-4 text-sm text-zinc-500">Source inventory will appear when processing starts.</div>}

        <section aria-label="Execution totals" className="grid grid-cols-3 overflow-hidden rounded-xl border border-white/10 bg-white/[0.02]">
          <MiniMetric label="Completed" value={completed} tone="text-emerald-300" />
          <MiniMetric label="Retries" value={retries} tone={retries ? "text-amber-300" : "text-zinc-300"} />
          <MiniMetric label="References" value={externalLookups} tone="text-violet-300" />
        </section>
        </div>
      </>}

      {!compact && (progress.completed_stages?.length ?? 0) > 0 && (
        <section aria-label="Completed stages">
          <p className="text-[10px] font-black uppercase tracking-[0.14em] text-zinc-500">Completed stages</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {(progress.completed_stages ?? []).map((stage) => (
              <span key={stage} className="inline-flex items-center gap-1.5 rounded-full border border-emerald-500/20 bg-emerald-500/10 px-3 py-1 text-xs font-bold text-emerald-300">
                <CheckCircle2 size={13} />{humanize(stage)}
              </span>
            ))}
          </div>
        </section>
      )}

      {progress.events.length ? (
        <ol aria-label="Agent turn details" className="relative space-y-4 before:absolute before:bottom-6 before:left-[1.15rem] before:top-6 before:w-px before:bg-white/10">
          {progress.events.map((event, index) => (
            <AgentTurnCard
              key={`${event.turn}-${event.name ?? event.type}-${index}`}
              event={event}
              nextEvent={progress.events[index + 1]}
              progressStatus={progress.status}
              compact={compact}
              defaultOpen={index === progress.events.length - 1}
            />
          ))}
        </ol>
      ) : (
        <div className="grid min-h-48 place-items-center rounded-xl border border-dashed border-white/15 bg-white/[0.02] px-6 text-center text-sm text-zinc-500">
          The agent has not completed a tool turn yet. This timeline updates while the job runs.
        </div>
      )}

      {progress.updated_at && (
        <p className="flex items-center justify-end gap-1.5 text-xs text-zinc-600">
          <Clock3 size={13} /> Trace updated {formatTimestamp(progress.updated_at)}
        </p>
      )}
    </div>
  );
}

function AgentTurnCard({ event, nextEvent, progressStatus, compact, defaultOpen }: { event: AgentEvent; nextEvent?: AgentEvent; progressStatus: string; compact: boolean; defaultOpen: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  const isUser = event.actor === "user" || event.type === "user_feedback";
  const failed = event.ok === false || event.type.endsWith("rejected");
  const Icon = isUser ? MessageSquareText : failed ? XCircle : event.name === "read_source_chunk" ? FileSearch : event.name === "submit_result" ? ShieldCheck : Activity;
  const title = isUser ? "Your guidance" : event.name ? humanize(event.name) : humanize(event.type);
  const inputDetails = event.input_details ?? {};
  const outputDetails = event.output_details ?? {};
  const hasStructuredDetails = Object.keys(inputDetails).length > 0 || Object.keys(outputDetails).length > 0;

  return (
    <li className="relative pl-12">
      <span className={`absolute left-0 top-4 z-10 grid h-9 w-9 place-items-center rounded-full border ${isUser ? "border-sky-500/30 bg-sky-500/15 text-sky-300" : failed ? "border-rose-500/30 bg-rose-500/15 text-rose-300" : "border-violet-500/30 bg-[#18181b] text-violet-300"}`}>
        <Icon size={16} />
      </span>
      <details open={open} onToggle={(event) => setOpen(event.currentTarget.open)} className={`group overflow-hidden rounded-xl border bg-white/[0.02] ${failed ? "border-rose-500/20" : "border-white/10"}`}>
        <summary className="focus-ring flex cursor-pointer list-none items-start justify-between gap-3 p-4 marker:content-none [&::-webkit-details-marker]:hidden">
          <div className="min-w-0">
              <p className={`font-mono text-[11px] font-bold uppercase tracking-[0.08em] ${isUser ? "text-sky-300" : "text-violet-300"}`}>
                {isUser ? "Review input" : `Turn ${event.turn}`}{event.stage ? ` · ${humanize(event.stage)}` : ""}
              </p>
              <h3 className="mt-1 truncate text-sm font-extrabold text-zinc-100">{title}</h3>
              <p className="mt-1 line-clamp-2 text-xs leading-5 text-zinc-500">{event.summary ?? fallbackSummary(event)}</p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <div className="text-right">
              <div className="flex items-center justify-end gap-2">
                {event.duration_ms != null && <span className="font-mono text-[11px] text-zinc-500">{formatDuration(event.duration_ms)}</span>}
                <span className={`inline-flex rounded-full px-2.5 py-1 text-[10px] font-black uppercase tracking-[0.08em] ${isUser ? "bg-sky-500/10 text-sky-300" : failed ? "bg-rose-500/10 text-rose-300" : "bg-emerald-500/10 text-emerald-300"}`}>
                  {isUser ? "Sent" : failed ? "Needs retry" : "Completed"}
                </span>
              </div>
              {event.occurred_at && <p className="mt-1 text-[11px] text-zinc-600">{formatTimestamp(event.occurred_at)}</p>}
            </div>
            <ChevronDown size={16} className="mt-1 text-zinc-500 transition-transform group-open:rotate-180" />
          </div>
        </summary>

        <div className="border-t border-white/[0.07] p-4 sm:p-5">

          <p className="text-sm leading-6 text-zinc-300">{event.summary ?? fallbackSummary(event)}</p>

          {event.intent && (
            <section className="mt-4 rounded-lg border border-violet-500/15 bg-violet-500/[0.05] p-3">
              <p className="text-[10px] font-black uppercase tracking-[0.12em] text-violet-300">Purpose of this turn</p>
              <p className="mt-1 text-sm leading-6 text-zinc-200">{event.intent}</p>
            </section>
          )}

          {(event.input_summary || event.output_summary) && !isUser && (
            <dl className={`mt-4 grid gap-3 ${compact ? "" : "md:grid-cols-2"}`}>
              {event.input_summary && <SummaryBlock label="Action requested" value={event.input_summary} />}
              {event.output_summary && <SummaryBlock label="Concrete outcome" value={event.output_summary} />}
            </dl>
          )}

          {(event.evidence?.length ?? 0) > 0 && (
            <section className="mt-4">
              <p className="text-[10px] font-black uppercase tracking-[0.12em] text-zinc-500">Evidence and checks used</p>
              <ul className="mt-2 flex flex-wrap gap-2">
                {(event.evidence ?? []).map((item) => <li key={item} className="rounded-full border border-sky-500/15 bg-sky-500/[0.06] px-2.5 py-1 text-xs text-sky-200">{item}</li>)}
              </ul>
            </section>
          )}

          {hasStructuredDetails && (
            <details open className="mt-4 rounded-lg border border-white/[0.08] bg-black/10">
              <summary className="cursor-pointer select-none px-3 py-2.5 text-xs font-bold text-zinc-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-violet-500">Structured action details</summary>
              <div className={`grid gap-px border-t border-white/[0.08] bg-white/[0.08] ${compact ? "" : "md:grid-cols-2"}`}>
                <DetailGroup title="Parameters sent" details={inputDetails} />
                <DetailGroup title="Facts returned" details={outputDetails} />
              </div>
            </details>
          )}

          {event.error && (
            <div className="mt-3 rounded-lg border border-rose-500/20 bg-rose-500/[0.07] px-3 py-2 text-xs leading-5 text-rose-300">
              <span className="font-bold">Error: </span>{event.error}
            </div>
          )}
        </div>

        <div className="border-t border-white/[0.07] bg-black/10 px-4 py-3 text-xs leading-5 sm:px-5">
          <span className="font-black uppercase tracking-[0.1em] text-zinc-600">What happened next · </span>
          <span className="text-zinc-400">{nextEvent ? nextEvent.intent ?? `The agent continued with ${humanize(nextEvent.name ?? nextEvent.type)}.` : terminalNextStep(failed, progressStatus)}</span>
        </div>
      </details>
    </li>
  );
}

function CompactOverview({ progress, sourceCoverage, completed, retries, externalLookups }: { progress: AgentProgress; sourceCoverage: number; completed: number; retries: number; externalLookups: number }) {
  return (
    <section aria-label="Agent execution summary" className="rounded-lg border border-white/10 bg-white/[0.025] p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-xs font-bold text-zinc-200">{progress.stage ? humanize(progress.stage) : "Preparing workflow"}</p>
          <p className="mt-0.5 truncate font-mono text-[10px] text-zinc-600">{progress.agent_id} · {progress.model ?? "Model not reported"}</p>
        </div>
        <span className={`rounded-full px-2 py-1 text-[9px] font-black uppercase tracking-[0.08em] ${progress.status === "completed" || progress.status === "succeeded" ? "bg-emerald-500/10 text-emerald-300" : "bg-violet-500/10 text-violet-300"}`}>
          {humanize(progress.status)}
        </span>
      </div>
      {progress.total_source_chunks > 0 && (
        <div className="mt-3">
          <div className="flex justify-between text-[10px] text-zinc-500"><span>Source review</span><span>{progress.read_source_chunks.length}/{progress.total_source_chunks}</span></div>
          <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-white/[0.08]"><div className="h-full rounded-full bg-violet-500" style={{ width: `${sourceCoverage}%` }} /></div>
        </div>
      )}
      <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1 border-t border-white/[0.07] pt-2 text-[10px] text-zinc-500">
        <span><strong className="text-zinc-300">{progress.turn}/{progress.max_turns}</strong> turns</span>
        <span><strong className="text-emerald-300">{completed}</strong> completed</span>
        <span><strong className={retries ? "text-amber-300" : "text-zinc-300"}>{retries}</strong> retries</span>
        <span><strong className="text-violet-300">{externalLookups}</strong> references</span>
        <span>{formatElapsed(progress.started_at, progress.updated_at)}</span>
      </div>
    </section>
  );
}

function SummaryBlock({ label, value }: { label: string; value: string }) {
  return <div className="rounded-lg border border-white/[0.08] bg-black/10 p-3"><dt className="text-[10px] font-black uppercase tracking-[0.12em] text-zinc-500">{label}</dt><dd className="mt-1 text-xs leading-5 text-zinc-300">{value}</dd></div>;
}

function DetailGroup({ title, details }: { title: string; details: Record<string, unknown> }) {
  return (
    <section className="bg-[#111113] p-3">
      <h4 className="text-[10px] font-black uppercase tracking-[0.12em] text-zinc-500">{title}</h4>
      {Object.keys(details).length ? (
        <dl className="mt-2 space-y-2">
          {Object.entries(details).map(([key, value]) => (
            <div key={key} className="grid gap-0.5 border-b border-white/[0.05] pb-2 last:border-0 last:pb-0">
              <dt className="text-[11px] font-bold text-zinc-400">{humanize(key)}</dt>
              <dd className="break-words text-xs leading-5 text-zinc-200">{renderDetailValue(value)}</dd>
            </div>
          ))}
        </dl>
      ) : <p className="mt-2 text-xs text-zinc-600">No structured details recorded.</p>}
    </section>
  );
}

function AgentMetric({ label, value, tone = "default" }: { label: string; value: string; tone?: "default" | "success" }) {
  return <div className="rounded-xl border border-white/10 bg-white/[0.025] p-4"><p className="text-[10px] font-black uppercase tracking-[0.12em] text-zinc-500">{label}</p><p className={`mt-1 break-words text-sm font-extrabold ${tone === "success" ? "text-emerald-300" : "text-zinc-200"}`}>{value}</p></div>;
}

function MiniMetric({ label, value, tone }: { label: string; value: number; tone: string }) {
  return <div className="grid place-items-center border-r border-white/10 p-4 text-center last:border-r-0"><p className={`text-2xl font-black ${tone}`}>{value}</p><p className="mt-1 text-[10px] font-black uppercase tracking-[0.1em] text-zinc-600">{label}</p></div>;
}

function renderDetailValue(value: unknown): string {
  if (Array.isArray(value)) return value.length ? value.map((item) => renderDetailValue(item)).join(" · ") : "None";
  if (value && typeof value === "object") return Object.entries(value as Record<string, unknown>).map(([key, item]) => `${humanize(key)}: ${renderDetailValue(item)}`).join(" · ");
  if (value === null || value === undefined || value === "") return "None";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}

function terminalNextStep(failed: boolean, status: string) {
  if (failed) return "The workflow will ask the agent to correct the request and try again.";
  if (status === "completed" || status === "succeeded") return "The agent finished this execution trace and returned the validated draft.";
  if (status === "review_required") return "The validated draft is waiting for human review.";
  return "Waiting for the agent's next approved action.";
}

function fallbackSummary(event: AgentEvent) {
  if (event.type === "plain_text_rejected") return "The response did not use an approved tool, so the workflow asked the agent to retry.";
  if (event.type === "multiple_tools_rejected") return "The workflow accepts one tool per turn and rejected the combined request.";
  return "The agent completed an approved workflow action.";
}

function humanize(value: string) {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatTimestamp(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "medium" }).format(date);
}

function formatDuration(milliseconds: number) {
  if (milliseconds < 1000) return `${milliseconds} ms`;
  if (milliseconds < 60_000) return `${(milliseconds / 1000).toFixed(1)} s`;
  return `${Math.floor(milliseconds / 60_000)}m ${Math.round((milliseconds % 60_000) / 1000)}s`;
}

function formatElapsed(start?: string | null, end?: string | null) {
  if (!start || !end) return "Not available";
  const milliseconds = new Date(end).getTime() - new Date(start).getTime();
  return Number.isFinite(milliseconds) && milliseconds >= 0 ? formatDuration(milliseconds) : "Not available";
}

const INTERNAL_TOOLS = new Set(["inspect_workflow_contract", "read_source_chunk", "submit_result"]);
