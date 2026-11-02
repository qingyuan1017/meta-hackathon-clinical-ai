import type { JobStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

const styles: Record<JobStatus, string> = {
  queued: "border-slate-300 bg-slate-100 text-slate-700",
  running: "border-blue-200 bg-blue-50 text-blue-700",
  review_required: "border-amber-200 bg-amber-50 text-amber-800",
  succeeded: "border-emerald-200 bg-emerald-50 text-emerald-700",
  failed: "border-rose-200 bg-rose-50 text-rose-700",
};

export function StatusBadge({ status, compact = false }: { status: JobStatus; compact?: boolean }) {
  return (
    <span className={cn("inline-flex shrink-0 items-center gap-1.5 rounded-sm border font-bold capitalize", compact ? "px-2 py-0.5 text-[10px]" : "px-2.5 py-1 text-xs", styles[status])}>
      <span className={cn("h-1.5 w-1.5 rounded-full bg-current", status === "running" && "animate-pulse")} />
      {status.replaceAll("_", " ")}
    </span>
  );
}
