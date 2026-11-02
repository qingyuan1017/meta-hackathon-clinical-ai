import { cn } from "@/lib/utils";

export function ExperimentalBadge({ compact = false }: { compact?: boolean }) {
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center rounded-full border border-amber-400/25 bg-amber-400/10 font-bold uppercase tracking-[0.1em] text-amber-300",
        compact ? "px-1.5 py-0.5 text-[8px]" : "px-2 py-1 text-[9px]",
      )}
    >
      Experimental
    </span>
  );
}
