"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, GitCompareArrows, X } from "lucide-react";
import { api } from "@/lib/api";
import { useReviewDraft } from "@/lib/review-draft-context";
import type { Job } from "@/lib/types";
import { Button } from "./ui/button";

export function ReviewPatchPanel({ job }: { job: Job }) {
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
  return (
    <section className="rounded-xl border border-amber-400/25 bg-amber-500/[0.07] p-4" aria-label="Scoped revision preview">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="flex items-center gap-2 text-sm font-extrabold text-amber-100"><GitCompareArrows size={17} />Scoped revision awaiting decision</p>
          <p className="mt-1 max-w-3xl text-xs leading-5 text-zinc-300">{patch.message}</p>
          <p className="mt-1 text-[11px] text-zinc-500">{patch.operations.length} changed path(s). Unlisted paths remain locked to the current draft.</p>
        </div>
        <span className="rounded-full border border-amber-400/20 bg-amber-400/10 px-2.5 py-1 text-[10px] font-black uppercase tracking-wider text-amber-200">{patch.stage.replaceAll("_", " ")}</span>
      </div>
      {patch.conflicts.length > 0 && <div className="mt-3 rounded-lg border border-rose-400/25 bg-rose-500/10 p-3 text-xs text-rose-200">The patch conflicts with newer edits: {patch.conflicts.join(", ")}. It was not applied.</div>}
      <div className="mt-4 max-h-80 space-y-2 overflow-auto pr-1">
        {patch.operations.map((operation, index) => (
          <article key={`${operation.path}-${index}`} className="rounded-lg border border-white/10 bg-black/20 p-3">
            <p className="break-all font-mono text-[11px] font-bold text-violet-200">{operation.path}</p>
            <div className="mt-2 grid gap-2 md:grid-cols-2">
              <PatchValue label="Current" value={operation.before} tone="text-rose-200" />
              <PatchValue label="Proposed" value={operation.after} tone="text-emerald-200" />
            </div>
          </article>
        ))}
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <Button type="button" variant="clinical" disabled={mutation.isPending || !job.result_revision} onClick={() => mutation.mutate(true)}><Check size={15} />Accept patch</Button>
        <Button type="button" variant="outline" disabled={mutation.isPending || !job.result_revision} onClick={() => mutation.mutate(false)}><X size={15} />Reject patch</Button>
        <span className="text-[11px] text-zinc-500">The stage remains unapproved after either decision.</span>
      </div>
      {mutation.error && <p className="mt-3 rounded-lg border border-rose-500/20 bg-rose-500/10 p-2 text-xs text-rose-300">{mutation.error.message}</p>}
    </section>
  );
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function PatchValue({ label, value, tone }: { label: string; value: unknown; tone: string }) {
  const rendered = value === undefined ? "Not present" : JSON.stringify(value, null, 2);
  return <div><p className="text-[10px] font-black uppercase tracking-wider text-zinc-500">{label}</p><pre className={`mt-1 max-h-36 overflow-auto whitespace-pre-wrap break-words rounded bg-black/30 p-2 text-[11px] ${tone}`}>{rendered}</pre></div>;
}
