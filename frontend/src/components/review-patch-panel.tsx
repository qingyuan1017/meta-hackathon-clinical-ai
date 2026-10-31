"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, GitCompareArrows, X } from "lucide-react";
import { api } from "@/lib/api";
import { useReviewDraft } from "@/lib/review-draft-context";
import type { Job, ReviewPatchOperation } from "@/lib/types";
import { Button } from "./ui/button";

export function ReviewPatchPanel({ job, domain, summaryOnly = false }: { job: Job; domain?: string; summaryOnly?: boolean }) {
  const patch = job.review_patch;
  const client = useQueryClient();
  const { currentResult } = useReviewDraft();
  const mutation = useMutation({
    mutationFn: (approved: boolean) => api.decideReviewPatch(
      job.id,
      patch!.transaction_id,
      approved,
      job.result_revision!,
      currentResult ?? asRecord(job.result),
    ),
    onSuccess: (updated) => {
      client.setQueryData(["job", job.id], updated);
      client.invalidateQueries({ queryKey: ["agent-progress", job.id] });
      client.invalidateQueries({ queryKey: ["jobs"] });
    },
  });
  if (!patch) return null;
  const allGroups = groupOperationsByDomain(patch.operations, asRecord(job.result));
  const operationGroups = domain ? allGroups.filter((group) => group.domain === domain) : allGroups;
  if (domain) return operationGroups.length ? <div className="mt-3"><DomainPatchSection group={operationGroups[0]} /></div> : null;
  return (
    <section className="rounded-xl border border-amber-400/25 bg-amber-500/[0.07] p-4" aria-label="Scoped revision preview">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="flex items-center gap-2 text-sm font-extrabold text-amber-100"><GitCompareArrows size={17} />Scoped revision awaiting decision</p>
          <p className="mt-1 max-w-3xl text-xs leading-5 text-zinc-300">{patch.message}</p>
          <p className="mt-1 text-[11px] text-zinc-500">{patch.operations.length} changed path(s) across {operationGroups.length} domain section(s). Unlisted paths remain locked to the current draft.</p>
        </div>
        <span className="rounded-full border border-amber-400/20 bg-amber-400/10 px-2.5 py-1 text-[10px] font-black uppercase tracking-wider text-amber-200">{patch.stage.replaceAll("_", " ")}</span>
      </div>
      {patch.conflicts.length > 0 && <div className="mt-3 rounded-lg border border-rose-400/25 bg-rose-500/10 p-3 text-xs text-rose-200">The patch conflicts with newer edits: {patch.conflicts.join(", ")}. It was not applied.</div>}
      {!summaryOnly && <div className="mt-4 max-h-[32rem] space-y-3 overflow-auto pr-1">{operationGroups.map((group) => <DomainPatchSection key={group.domain} group={group} />)}</div>}
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <Button type="button" variant="clinical" disabled={mutation.isPending || !job.result_revision} onClick={() => mutation.mutate(true)}><Check size={15} />Accept all domain sections</Button>
        <Button type="button" variant="outline" disabled={mutation.isPending || !job.result_revision} onClick={() => mutation.mutate(false)}><X size={15} />Reject all domain sections</Button>
        <span className="text-[11px] text-zinc-500">The patch is one transaction; this decision covers every domain section and does not approve the stage.</span>
      </div>
      {mutation.error && <p className="mt-3 rounded-lg border border-rose-500/20 bg-rose-500/10 p-2 text-xs text-rose-300">{mutation.error.message}</p>}
    </section>
  );
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

interface OperationGroup { domain: string; operations: ReviewPatchOperation[]; }

function DomainPatchSection({ group }: { group: OperationGroup }) {
  return <section className="overflow-hidden rounded-xl border border-violet-400/20 bg-black/15" aria-label={`${group.domain} feedback decision`}>
    <header className="flex items-center justify-between border-b border-white/10 bg-violet-500/[0.07] px-3 py-2.5">
      <div><p className="font-mono text-xs font-black text-violet-200">{group.domain}</p><p className="mt-0.5 text-[10px] text-zinc-500">Feedback decision · {group.operations.length} changed path(s)</p></div>
      <span className="rounded-full border border-violet-400/20 px-2 py-1 text-[9px] font-black uppercase tracking-wider text-violet-300">{group.domain === "General" ? "Stage-wide" : group.domain === "Not mapped" ? "Source disposition" : "SDTM domain"}</span>
    </header>
    <div className="space-y-2 p-3">{group.operations.map((operation, index) => (
      <article key={`${operation.path}-${index}`} className="rounded-lg border border-white/10 bg-black/20 p-3">
        <p className="break-all font-mono text-[11px] font-bold text-violet-200">{operation.path}</p>
        <div className="mt-2 grid gap-2 md:grid-cols-2">
          <PatchValue label="Current" value={operation.before} tone="text-rose-200" />
          <PatchValue label="Proposed" value={operation.after} tone="text-emerald-200" />
        </div>
      </article>
    ))}</div>
  </section>;
}

export function groupOperationsByDomain(operations: ReviewPatchOperation[], result: Record<string, unknown>): OperationGroup[] {
  const groups = new Map<string, ReviewPatchOperation[]>();
  for (const operation of operations) {
    const domain = operationDomain(operation, result);
    groups.set(domain, [...(groups.get(domain) ?? []), operation]);
  }
  return Array.from(groups, ([domain, grouped]) => ({ domain, operations: grouped }))
    .sort((left, right) => left.domain === "General" ? 1 : right.domain === "General" ? -1 : left.domain.localeCompare(right.domain));
}

function operationDomain(operation: ReviewPatchOperation, result: Record<string, unknown>): string {
  if (operation.path.includes("/unmapped_datasets/")) return "Not mapped";
  const pathDomain = operation.path.match(/\/(?:domain|target_domain)=([^/]+)/i)?.[1];
  if (pathDomain) return decodePointer(pathDomain).toUpperCase();
  const valueDomain = domainFromValue(operation.after) ?? domainFromValue(operation.before);
  if (valueDomain) return valueDomain;
  if (operation.path.endsWith("/target_domain")) {
    const target = typeof operation.after === "string" ? operation.after : operation.before;
    if (typeof target === "string" && target.trim()) return target.trim().toUpperCase();
  }
  const source = operation.path.match(/\/source_dataset=([^/]+)/i)?.[1];
  if (source) {
    const envelope = asRecord(result.domain_mapping);
    const mappings = Array.isArray(envelope.domain_mappings) ? envelope.domain_mappings : [];
    const match = mappings.find((item) => {
      const mapping = asRecord(item);
      return String(mapping.source_dataset ?? "").toUpperCase() === decodePointer(source).toUpperCase();
    });
    const target = asRecord(match).target_domain;
    if (typeof target === "string" && target.trim()) return target.trim().toUpperCase();
  }
  return "General";
}

function domainFromValue(value: unknown): string | null {
  const record = asRecord(value);
  const domain = record.domain ?? record.target_domain;
  return typeof domain === "string" && domain.trim() ? domain.trim().toUpperCase() : null;
}

function decodePointer(value: string): string { return value.replaceAll("~1", "/").replaceAll("~0", "~"); }

function PatchValue({ label, value, tone }: { label: string; value: unknown; tone: string }) {
  const rendered = value === undefined ? "Not present" : JSON.stringify(value, null, 2);
  return <div><p className="text-[10px] font-black uppercase tracking-wider text-zinc-500">{label}</p><pre className={`mt-1 max-h-36 overflow-auto whitespace-pre-wrap break-words rounded bg-black/30 p-2 text-[11px] ${tone}`}>{rendered}</pre></div>;
}
