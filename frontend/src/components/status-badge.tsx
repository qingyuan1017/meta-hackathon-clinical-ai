import type { JobStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

const styles: Record<JobStatus, string> = {
  queued: "bg-slate-100 text-slate-700",
  running: "bg-blue-50 text-blue-700",
  succeeded: "bg-emerald-50 text-emerald-700",
  failed: "bg-rose-50 text-rose-700",
};

export function StatusBadge({ status }: { status: JobStatus }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-bold capitalize", styles[status])}>
      <span className={cn("h-1.5 w-1.5 rounded-full bg-current", status === "running" && "animate-pulse")} />
      {status}
    </span>
  );
}
