"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, LoaderCircle, Server, Unplug } from "lucide-react";
import { api } from "@/lib/api";

export function ConfigStatus({
  compact = false,
  tone = "light",
  inline = false,
}: {
  compact?: boolean;
  tone?: "light" | "dark";
  inline?: boolean;
}) {
  const query = useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 30_000 });
  const configured = query.data?.meta_configured === true;
  const loading = query.isPending;
  const failed = query.isError;
  const title = loading ? "Checking Meta configuration" : failed ? "Backend connection unavailable" : configured ? "Meta generation is ready" : "Meta configuration required";
  const Icon = loading ? LoaderCircle : failed ? Unplug : configured ? CheckCircle2 : AlertTriangle;
  const dark = tone === "dark";

  if (inline) {
    return (
      <div role="status" className="flex items-center gap-2 whitespace-nowrap">
        <Icon
          className={`${loading ? "animate-spin" : ""} ${configured ? "text-emerald-500" : failed ? "text-rose-500" : "text-amber-500"}`}
          size={14}
          aria-hidden="true"
        />
        <span className={`text-xs font-medium ${dark ? "text-zinc-400" : "text-zinc-600"}`}>{title}</span>
      </div>
    );
  }

  return (
    <div className={`rounded-xl border p-4 ${dark ? "border-white/10 bg-white/[0.04]" : configured ? "border-emerald-500/25 bg-emerald-500/[0.08]" : failed ? "border-rose-500/25 bg-rose-500/[0.08]" : "border-amber-500/25 bg-amber-500/[0.08]"}`}>
      <div className="flex items-start gap-3">
        <Icon className={`mt-0.5 ${loading ? "animate-spin" : ""} ${configured ? "text-emerald-500" : failed ? "text-rose-500" : "text-amber-500"}`} size={18} />
        <div className="min-w-0">
          <p className="text-xs font-bold text-zinc-200">{title}</p>
          {!compact && (
            <p className={`mt-1 text-xs leading-5 ${dark ? "text-zinc-500" : "text-zinc-400"}`}>
              {loading ? "Reading the API service status…" : failed ? "The browser could not reach the API health endpoint." : configured
                ? <><Server className="mr-1 inline" size={13} /> Model: {query.data?.meta_model}</>
                : "Set META_API_KEY and META_MODEL on the API service. Generation is disabled until both are present."}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
