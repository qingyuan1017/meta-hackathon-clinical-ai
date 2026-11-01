"use client";

import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Bot, CheckCircle2, Circle, Info } from "lucide-react";
import { ConfigStatus } from "@/components/config-status";
import { AgentActivitySidebar } from "@/components/agent-activity-sidebar";
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
  if (!definition) return <div className="mx-auto max-w-3xl px-5 py-20"><h1 className="text-2xl font-bold">Workflow not found</h1><Link href="/" className="mt-4 inline-block text-clinical-700">Return home</Link></div>;
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
      <div className="border-b border-white/10 pb-6">
        <p className="text-xs font-semibold uppercase tracking-[0.14em] text-clinical-700">{workspaceLabel} / {definition.shortTitle}</p>
        <div className="mt-2 flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
          <div><h1 className="text-3xl font-semibold tracking-[-0.03em] text-white">{definition.title}</h1><p className="mt-2 max-w-2xl text-sm leading-6 text-zinc-400">{definition.description}</p></div>
          <Link href="/" className="focus-ring text-sm font-medium text-zinc-500 hover:text-white">All modules</Link>
        </div>
      </div>
      <div className={`mt-7 grid items-start gap-7 xl:grid-cols-[260px_minmax(0,1fr)] ${agentHistoryOpen ? "2xl:grid-cols-[240px_minmax(0,1fr)_380px]" : ""}`}>
        <aside>
          <div className="rounded-xl border border-white/10 bg-[#18181b] p-5 shadow-sm">
            <div className="grid h-10 w-10 place-items-center rounded-lg bg-clinical-500/15 text-violet-300"><Icon size={19} /></div>
            <p className="mt-5 text-[10px] font-bold uppercase tracking-[0.16em] text-zinc-400">{definition.eyebrow}</p>
            <p className="mt-2 text-sm font-semibold leading-5 text-zinc-100">Specialist generation agent</p>
            <p className="mt-2 text-xs leading-5 text-zinc-400">Inputs are validated before the agent starts. Outputs follow the workflow schema before artifacts are rendered.</p>
          </div>
          <div className="mt-4"><WorkflowJobHistory workflow={workflow} currentJobId={jobId} discipline={discipline} /></div>
          <div className="mt-4"><ConfigStatus compact /></div>
          <div className="mt-4 rounded-xl border border-white/10 bg-[#18181b] p-4">
            <p className="flex items-center gap-2 text-xs font-semibold text-zinc-100"><Info size={15} className="text-violet-300" /> Agent execution contract</p>
            <ol className="mt-4 space-y-3 text-xs text-zinc-600">{executionSteps.map((step, index) => <li key={step} className="flex items-center gap-2">{jobId && ((jobQuery.data?.status === "succeeded") || index === 0) ? <CheckCircle2 size={14} className="text-clinical-600" /> : <Circle size={14} className="text-zinc-300" />}{step}</li>)}</ol>
          </div>
          {contract.data && (
            <div className="mt-4 rounded-xl border border-white/10 bg-[#18181b] p-4">
              <p className="text-xs font-semibold text-zinc-100">Shared use-case contract</p>
              <p className="mt-3 flex items-start gap-2 text-xs leading-5 text-zinc-400"><Bot size={14} className="mt-0.5 shrink-0 text-violet-300" /><span>Agent: <span className="font-semibold text-zinc-100">{contract.data.agent_name}</span><br /><span className="font-mono text-[11px] text-violet-300">{contract.data.agent_id}</span></span></p>
              <p className="mt-2 text-xs leading-5 text-zinc-400">Skill: <span className="font-mono text-violet-300">{contract.data.skill_name}</span></p>
              {contract.data.stages && contract.data.stages.length > 0 && <p className="mt-2 text-xs leading-5 text-zinc-400">Stages: {contract.data.stages.join(" → ")}</p>}
              <p className="mt-2 text-xs leading-5 text-zinc-400">Outputs: {contract.data.output_formats.join(", ").toUpperCase()}</p>
              <p className="mt-2 text-xs leading-5 text-zinc-400">Result editing: {contract.data.supports_result_editing ? "schema-validated" : "disabled"}</p>
            </div>
          )}
        </aside>
        <section className="min-w-0">
          {jobId && jobQuery.data ? <ResultView job={jobQuery.data} onReset={reset} /> : jobId && jobQuery.isLoading ? <div className="grid min-h-96 place-items-center rounded-xl border border-white/10 bg-[#18181b] text-sm text-zinc-500">Loading job…</div> : <WorkflowForm workflow={workflow} discipline={discipline} enabled={Boolean(health.data?.meta_configured)} onCreated={onCreated} />}
          {jobQuery.error && <div className="rounded-xl border border-rose-500/25 bg-rose-500/10 p-4 text-sm text-rose-300">{jobQuery.error.message}</div>}
        </section>
        {jobId && jobQuery.data && <AgentActivitySidebar job={jobQuery.data} onOpenChange={setAgentHistoryOpen} />}
      </div>
    </div>
    </ReviewDraftProvider>
  );
}
