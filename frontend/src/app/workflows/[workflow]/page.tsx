"use client";

import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Bot, CheckCircle2, Circle, Info } from "lucide-react";
import { ConfigStatus } from "@/components/config-status";
import { ResultView } from "@/components/result-view";
import { WorkflowForm } from "@/components/workflow-form";
import { api } from "@/lib/api";
import type { Job, Workflow } from "@/lib/types";
import { workflowById } from "@/lib/workflows";

export default function WorkflowPage() {
  const params = useParams<{ workflow: string }>();
  const search = useSearchParams();
  const router = useRouter();
  const workflow = params.workflow as Workflow;
  const definition = workflowById[workflow];
  const jobId = search.get("job");
  const health = useQuery({ queryKey: ["health"], queryFn: api.health });
  const contract = useQuery({
    queryKey: ["use-case", workflow],
    queryFn: () => api.useCase(workflow),
    enabled: Boolean(definition),
  });
  const jobQuery = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => api.job(jobId!),
    enabled: Boolean(jobId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "queued" || status === "running" ? 2_000 : false;
    },
  });
  if (!definition) return <div className="mx-auto max-w-3xl px-5 py-20"><h1 className="text-2xl font-bold">Workflow not found</h1><Link href="/" className="mt-4 inline-block text-clinical-700">Return home</Link></div>;
  const Icon = definition.icon;
  const onCreated = (job: Job) => router.replace(`/workflows/${workflow}?job=${job.id}`);
  const reset = () => router.replace(`/workflows/${workflow}`);
  return (
    <div className="mx-auto max-w-7xl px-5 py-10 lg:px-8 lg:py-14">
      <Link href="/" className="focus-ring inline-flex items-center gap-2 rounded-lg text-sm font-bold text-slate-500 hover:text-ink"><ArrowLeft size={16} /> All workbenches</Link>
      <div className="mt-6 grid gap-8 lg:grid-cols-[280px_1fr]">
        <aside>
          <div className="rounded-2xl bg-ink p-6 text-white shadow-soft">
            <div className="grid h-11 w-11 place-items-center rounded-xl bg-white/10"><Icon size={21} /></div>
            <p className="mt-6 text-[11px] font-black tracking-[0.18em] text-emerald-300">{definition.eyebrow}</p>
            <h1 className="mt-2 text-2xl font-extrabold leading-tight tracking-tight">{definition.title}</h1>
            <p className="mt-4 text-sm leading-6 text-slate-300">{definition.description}</p>
          </div>
          <div className="mt-4"><ConfigStatus compact /></div>
          <div className="mt-4 rounded-xl border border-slate-200 bg-white p-4">
            <p className="flex items-center gap-2 text-xs font-extrabold text-ink"><Info size={15} className="text-clinical-700" /> Agent execution contract</p>
            <ol className="mt-4 space-y-3 text-xs text-slate-600">{["Validate and scan input", "Inspect workflow contract", "Investigate all source chunks", "Validate and render artifacts"].map((step, index) => <li key={step} className="flex items-center gap-2">{jobId && ((jobQuery.data?.status === "succeeded") || index === 0) ? <CheckCircle2 size={14} className="text-clinical-600" /> : <Circle size={14} className="text-slate-300" />}{step}</li>)}</ol>
          </div>
          {contract.data && (
            <div className="mt-4 rounded-xl border border-slate-200 bg-white p-4">
              <p className="text-xs font-extrabold text-ink">Shared use-case contract</p>
              <p className="mt-3 flex items-start gap-2 text-xs leading-5 text-slate-600"><Bot size={14} className="mt-0.5 shrink-0 text-clinical-700" /><span>Agent: <span className="font-semibold text-ink">{contract.data.agent_name}</span><br /><span className="font-mono text-[11px] text-clinical-700">{contract.data.agent_id}</span></span></p>
              <p className="mt-2 text-xs leading-5 text-slate-600">Skill: <span className="font-mono text-clinical-700">{contract.data.skill_name}</span></p>
              <p className="mt-2 text-xs leading-5 text-slate-600">Outputs: {contract.data.output_formats.join(", ").toUpperCase()}</p>
              <p className="mt-2 text-xs leading-5 text-slate-600">Result editing: {contract.data.supports_result_editing ? "schema-validated" : "disabled"}</p>
            </div>
          )}
        </aside>
        <section>
          {jobId && jobQuery.data ? <ResultView job={jobQuery.data} onReset={reset} /> : jobId && jobQuery.isLoading ? <div className="grid min-h-96 place-items-center rounded-2xl border border-slate-200 bg-white text-sm text-slate-500">Loading job…</div> : <WorkflowForm workflow={workflow} enabled={Boolean(health.data?.meta_configured)} onCreated={onCreated} />}
          {jobQuery.error && <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">{jobQuery.error.message}</div>}
        </section>
      </div>
    </div>
  );
}
