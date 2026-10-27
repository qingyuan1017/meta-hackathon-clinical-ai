"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight, Clock3 } from "lucide-react";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/utils";
import { StatusBadge } from "./status-badge";

export function RecentJobs() {
  const query = useQuery({ queryKey: ["jobs"], queryFn: () => api.jobs(), refetchInterval: 5_000 });
  const jobs = query.data?.items.slice(0, 6) ?? [];
  return (
    <section aria-labelledby="recent-heading">
      <div className="mb-4 flex items-end justify-between">
        <div>
          <p className="text-xs font-extrabold tracking-[0.16em] text-clinical-700">LOCAL HISTORY</p>
          <h2 id="recent-heading" className="mt-1 text-2xl font-extrabold tracking-tight text-zinc-100">Recent generation jobs</h2>
        </div>
      </div>
      <div className="overflow-hidden rounded-2xl border border-white/10 bg-[#18181b] shadow-soft">
        {jobs.length ? jobs.map((job, index) => (
          <Link
            href={`/workflows/${job.workflow}?job=${job.id}`}
            key={job.id}
            className={`focus-ring flex items-center justify-between gap-4 px-5 py-4 transition hover:bg-white/[0.04] ${index ? "border-t border-white/[0.08]" : ""}`}
          >
            <div className="min-w-0">
              <p className="truncate text-sm font-bold text-zinc-200">{job.title}</p>
              <p className="mt-1 flex items-center gap-1.5 text-xs text-zinc-500"><Clock3 size={12} /> {formatDate(job.created_at)}</p>
            </div>
            <div className="flex items-center gap-3"><StatusBadge status={job.status} /><ArrowUpRight size={16} className="text-zinc-500" /></div>
          </Link>
        )) : (
          <div className="px-6 py-10 text-center text-sm text-zinc-500">No jobs yet. Choose a workflow above to create the first draft.</div>
        )}
      </div>
    </section>
  );
}
