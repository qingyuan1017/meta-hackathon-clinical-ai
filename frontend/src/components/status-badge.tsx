import type { JobStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

const styles: Record<JobStatus, string> = {
  queued: "bg-zinc-500/15 text-zinc-300",
  running: "bg-blue-500/15 text-blue-300",
  review_required: "bg-amber-500/15 text-amber-300",
  succeeded: "bg-emerald-500/15 text-emerald-300",
  failed: "bg-rose-500/15 text-rose-300",
};

export function StatusBadge({ status, compact = false }: { status: JobStatus; compact?: boolean }) {
  return (
    <span className={cn("inline-flex shrink-0 items-center gap-1.5 rounded-full font-bold capitalize", compact ? "px-2 py-0.5 text-[10px]" : "px-2.5 py-1 text-xs", styles[status])}>
      <span className={cn("h-1.5 w-1.5 rounded-full bg-current", status === "running" && "animate-pulse")} />
      {status.replaceAll("_", " ")}
    </span>
  );
}
