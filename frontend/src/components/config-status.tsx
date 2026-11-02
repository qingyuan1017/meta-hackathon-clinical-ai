"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, LoaderCircle, Server, Unplug } from "lucide-react";
import { api } from "@/lib/api";

export function ConfigStatus({ compact = false, tone = "light" }: { compact?: boolean; tone?: "light" | "dark" }) {
  const query = useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 30_000 });
  const configured = query.data?.meta_configured === true;
  const loading = query.isPending;
  const failed = query.isError;
  const title = loading ? "Checking processing service" : failed ? "Service unavailable" : configured ? "Processing service ready" : "Configuration required";
  const Icon = loading ? LoaderCircle : failed ? Unplug : configured ? CheckCircle2 : AlertTriangle;
  const dark = tone === "dark";
  return (
    <div className={`border p-4 ${dark ? "border-[#315a55] bg-[#204a45]" : configured ? "border-emerald-200 bg-emerald-50/70" : failed ? "border-rose-200 bg-rose-50/70" : "border-amber-200 bg-amber-50/70"}`}>
      <div className="flex items-start gap-3">
        <Icon className={`mt-0.5 ${loading ? "animate-spin" : ""} ${configured ? "text-emerald-500" : failed ? "text-rose-500" : "text-amber-500"}`} size={18} />
        <div className="min-w-0">
          <p className={`text-xs font-bold ${dark ? "text-white" : "text-slate-800"}`}>{title}</p>
          {!compact && (
            <p className={`mt-1 text-xs leading-5 ${dark ? "text-[#9db2ad]" : "text-slate-500"}`}>
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
