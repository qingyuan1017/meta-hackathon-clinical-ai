"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Server } from "lucide-react";
import { api } from "@/lib/api";

export function ConfigStatus({ compact = false }: { compact?: boolean }) {
  const query = useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 30_000 });
  const configured = query.data?.meta_configured;
  return (
    <div className={`rounded-xl border p-4 ${configured ? "border-emerald-200 bg-emerald-50/70" : "border-amber-200 bg-amber-50/80"}`}>
      <div className="flex items-start gap-3">
        {configured ? <CheckCircle2 className="mt-0.5 text-emerald-700" size={19} /> : <AlertTriangle className="mt-0.5 text-amber-700" size={19} />}
        <div className="min-w-0">
          <p className="text-sm font-extrabold text-ink">{configured ? "Meta generation is ready" : "Meta configuration required"}</p>
          {!compact && (
            <p className="mt-1 text-xs leading-5 text-slate-600">
              {configured
                ? <><Server className="mr-1 inline" size={13} /> Model: {query.data?.meta_model}</>
                : "Set META_API_KEY and META_MODEL on the API service. Generation is disabled until both are present."}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
