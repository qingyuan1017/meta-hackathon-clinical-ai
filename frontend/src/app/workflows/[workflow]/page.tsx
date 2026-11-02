"use client";

import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { CheckCircle2, Circle, FileCheck2, Info } from "lucide-react";
import { ConfigStatus } from "@/components/config-status";
import { AgentActivitySidebar } from "@/components/agent-activity-sidebar";
import { ExperimentalBadge } from "@/components/experimental-badge";
import { ResultView } from "@/components/result-view";
import { WorkflowForm } from "@/components/workflow-form";
import { WorkflowJobHistory } from "@/components/workflow-job-history";
import { api } from "@/lib/api";
import type { Job, Workflow } from "@/lib/types";
import { workflowById } from "@/lib/workflows";
import { ReviewDraftProvider } from "@/lib/review-draft-context";

export default function WorkflowPage() {
  const params = useParams<{ workflow: string }>();
  const search = useSearchParams();
  const router = useRouter();
  const workflow = params.workflow as Workflow;
  const definition = workflowById[workflow];
  const jobId = search.get("job");
  const [agentHistoryOpen, setAgentHistoryOpen] = useState(false);
  const discipline = search.get("discipline") ?? "biostats";
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
  useEffect(() => setAgentHistoryOpen(false), [jobId]);
  if (!definition) return <div className="mx-auto max-w-3xl px-5 py-20"><h1 className="text-2xl font-bold text-slate-900">Workflow not found</h1><Link href="/" className="mt-4 inline-block text-clinical-700">Return home</Link></div>;
  const Icon = definition.icon;
  const disciplineQuery = workflow === "clinical-document" ? `&discipline=${discipline}` : "";
  const onCreated = (job: Job) => router.replace(`/workflows/${workflow}?job=${job.id}${disciplineQuery}`);
  const reset = () => router.replace(`/workflows/${workflow}${workflow === "clinical-document" ? `?discipline=${discipline}` : ""}`);
  const workspaceLabel = workflow === "clinical-document" && discipline === "data-management" ? "Data management" : workflow === "sdtm" || workflow === "tlf" ? "Stats programming" : "Biostats";
  const executionSteps = workflow === "sdtm"
    ? ["Validate and scan input", "Normalize EDC source specification", "User source review", "Draft domain mapping", "User domain review", "Draft variable & value-level mapping", "User variable & VLM review", "Rule augmentation", "Validate and render artifacts"]
    : workflow === "tlf"
      ? ["Validate and scan input", "Output table of contents", "User inventory review", "Detailed shell generation", "User shell review", "ADaM-linked programming", "User programming review", "Validate and render artifacts"]
    : ["Validate and scan input", "Inspect workflow contract", "Investigate all source chunks", "Validate and render artifacts"];
  return (
    <ReviewDraftProvider jobId={jobId}>
    <div className="mx-auto max-w-[1840px] px-5 py-8 lg:px-10 lg:py-10">
      <div className="border-b border-slate-300 pb-7">
        <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-[#b6533c]">{workspaceLabel} / {definition.shortTitle}</p>
        <div className="mt-2 flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
          <div><div className="flex flex-wrap items-center gap-3"><h1 className="editorial-title text-3xl text-slate-900 sm:text-4xl">{definition.title}</h1>{definition.experimental && <ExperimentalBadge />}</div><p className="mt-3 max-w-2xl text-sm leading-6 text-slate-600">{definition.description}</p></div>
          <Link href="/" className="focus-ring text-sm font-semibold text-slate-500 hover:text-[#1f6b62]">All workstreams</Link>
        </div>
      </div>
      <div className={`mt-7 grid items-start gap-7 xl:grid-cols-[260px_minmax(0,1fr)] ${agentHistoryOpen ? "2xl:grid-cols-[240px_minmax(0,1fr)_380px]" : ""}`}>
        <aside>
          <div className="border border-slate-300 bg-[#fffefa] p-5 shadow-soft">
            <div className="grid h-9 w-9 place-items-center rounded-sm bg-[#e2eee9] text-[#1f6b62]"><Icon size={18} strokeWidth={1.8} /></div>
            <p className="mt-5 text-[10px] font-bold uppercase tracking-[0.16em] text-[#b6533c]">{definition.eyebrow}</p>
            <p className="mt-2 text-sm font-semibold leading-5 text-slate-900">Controlled artifact workflow</p>
            <p className="mt-2 text-xs leading-5 text-slate-500">Source inputs are checked before processing. Results must meet the workflow schema before exports are prepared.</p>
          </div>
          <div className="mt-4"><WorkflowJobHistory workflow={workflow} currentJobId={jobId} discipline={discipline} /></div>
          <div className="mt-4"><ConfigStatus compact /></div>
          <div className="mt-4 border border-slate-300 bg-[#fffefa] p-4">
            <p className="flex items-center gap-2 text-xs font-semibold text-slate-900"><Info size={15} className="text-[#1f6b62]" /> Processing sequence</p>
            <ol className="mt-4 space-y-3 text-xs text-slate-500">{executionSteps.map((step, index) => <li key={step} className="flex items-center gap-2">{jobId && ((jobQuery.data?.status === "succeeded") || index === 0) ? <CheckCircle2 size={14} className="text-clinical-600" /> : <Circle size={14} className="text-slate-300" />}{step}</li>)}</ol>
          </div>
          {contract.data && (
            <div className="mt-4 border border-slate-300 bg-[#fffefa] p-4">
              <p className="text-xs font-semibold text-slate-900">Workflow contract</p>
              <p className="mt-3 flex items-start gap-2 text-xs leading-5 text-slate-600"><FileCheck2 size={14} className="mt-0.5 shrink-0 text-[#1f6b62]" /><span>Processor: <span className="font-semibold text-slate-900">{contract.data.agent_name}</span><br /><span className="font-mono text-[11px] text-[#1f6b62]">{contract.data.agent_id}</span></span></p>
              <p className="mt-2 text-xs leading-5 text-slate-600">Method: <span className="font-mono text-[#1f6b62]">{contract.data.skill_name}</span></p>
              {contract.data.stages && contract.data.stages.length > 0 && <p className="mt-2 text-xs leading-5 text-slate-600">Stages: {contract.data.stages.join(" → ")}</p>}
              <p className="mt-2 text-xs leading-5 text-slate-600">Outputs: {contract.data.output_formats.join(", ").toUpperCase()}</p>
              <p className="mt-2 text-xs leading-5 text-slate-600">Result editing: {contract.data.supports_result_editing ? "schema-validated" : "disabled"}</p>
            </div>
          )}
        </aside>
        <section className="min-w-0">
          {jobId && jobQuery.data ? <ResultView job={jobQuery.data} onReset={reset} /> : jobId && jobQuery.isLoading ? <div className="grid min-h-96 place-items-center border border-slate-300 bg-[#fffefa] text-sm text-slate-500">Loading job…</div> : <WorkflowForm workflow={workflow} discipline={discipline} enabled={Boolean(health.data?.meta_configured)} onCreated={onCreated} />}
          {jobQuery.error && <div className="rounded-xl border border-rose-500/25 bg-rose-500/10 p-4 text-sm text-rose-300">{jobQuery.error.message}</div>}
        </section>
        {jobId && jobQuery.data && <AgentActivitySidebar job={jobQuery.data} onOpenChange={setAgentHistoryOpen} />}
      </div>
    </div>
    </ReviewDraftProvider>
  );
}
