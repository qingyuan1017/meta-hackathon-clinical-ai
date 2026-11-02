"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Clock3, Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Workflow } from "@/lib/types";
import { cn, formatDate } from "@/lib/utils";
import { StatusBadge } from "./status-badge";

const PAGE_SIZE = 6;

interface WorkflowJobHistoryProps {
  workflow: Workflow;
  currentJobId: string | null;
  discipline?: string;
}

export function WorkflowJobHistory({ workflow, currentJobId, discipline }: WorkflowJobHistoryProps) {
  const [page, setPage] = useState(1);
  const query = useQuery({
    queryKey: ["jobs", workflow, page],
    queryFn: () => api.jobs(workflow, page, PAGE_SIZE),
    refetchInterval: 5_000,
  });
  const totalPages = Math.max(1, Math.ceil((query.data?.total ?? 0) / PAGE_SIZE));
  const disciplineQuery = workflow === "clinical-document" && discipline
    ? `&discipline=${encodeURIComponent(discipline)}`
    : "";
  const newJobHref = workflow === "clinical-document" && discipline
    ? `/workflows/${workflow}?discipline=${encodeURIComponent(discipline)}`
    : `/workflows/${workflow}`;

  useEffect(() => {
    if (query.data && page > totalPages) setPage(totalPages);
  }, [page, query.data, totalPages]);

  return (
    <section className="overflow-hidden rounded-xl border border-white/10 bg-[#18181b] shadow-sm" aria-labelledby="module-jobs-heading">
      <div className="flex items-center justify-between gap-3 border-b border-white/[0.08] px-4 py-4">
        <div>
          <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-zinc-500">Module history</p>
          <h2 id="module-jobs-heading" className="mt-1 text-sm font-semibold text-zinc-100">
            Jobs <span className="font-normal text-zinc-500">({query.data?.total ?? 0})</span>
          </h2>
        </div>
        <Link href={newJobHref} className="focus-ring inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.04] px-2.5 py-2 text-xs font-semibold text-zinc-200 transition hover:bg-white/[0.08]">
          <Plus size={14} /> New
        </Link>
      </div>

      <div className="p-2">
        {query.isLoading ? (
          <p className="px-3 py-6 text-center text-xs text-zinc-500">Loading module jobs…</p>
        ) : query.error ? (
          <p className="px-3 py-6 text-center text-xs text-rose-300">Unable to load this module&apos;s jobs.</p>
        ) : query.data?.items.length ? (
          <div className="space-y-1">
            {query.data.items.map((job) => (
              <Link
                key={job.id}
                href={`/workflows/${workflow}?job=${job.id}${disciplineQuery}`}
                aria-current={job.id === currentJobId ? "page" : undefined}
                className={cn(
                  "focus-ring block rounded-lg border px-3 py-3 transition",
                  job.id === currentJobId
                    ? "border-clinical-500/50 bg-clinical-500/10"
                    : "border-transparent hover:border-white/10 hover:bg-white/[0.04]",
                )}
              >
                <div className="flex items-start justify-between gap-2">
                  <p className="min-w-0 truncate text-xs font-semibold text-zinc-200">{job.title}</p>
                  <StatusBadge status={job.status} compact />
                </div>
                <p className="mt-1.5 flex items-center gap-1.5 text-[11px] text-zinc-600">
                  <Clock3 size={11} /> {formatDate(job.created_at)}
                </p>
              </Link>
            ))}
          </div>
        ) : (
          <p className="px-3 py-6 text-center text-xs leading-5 text-zinc-500">No jobs in this module yet.</p>
        )}
      </div>

      {totalPages > 1 && (
        <div className="flex items-center justify-between border-t border-white/[0.08] px-3 py-3">
          <button type="button" aria-label="Previous jobs page" onClick={() => setPage((value) => Math.max(1, value - 1))} disabled={page === 1} className="focus-ring grid h-8 w-8 place-items-center rounded-lg text-zinc-400 transition hover:bg-white/[0.06] hover:text-white disabled:cursor-not-allowed disabled:opacity-30">
            <ChevronLeft size={15} />
          </button>
          <span className="text-[11px] font-medium text-zinc-500">Page {page} of {totalPages}</span>
          <button type="button" aria-label="Next jobs page" onClick={() => setPage((value) => Math.min(totalPages, value + 1))} disabled={page === totalPages} className="focus-ring grid h-8 w-8 place-items-center rounded-lg text-zinc-400 transition hover:bg-white/[0.06] hover:text-white disabled:cursor-not-allowed disabled:opacity-30">
            <ChevronRight size={15} />
          </button>
        </div>
      )}
    </section>
  );
}
