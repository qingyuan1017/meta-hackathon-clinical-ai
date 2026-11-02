"use client";

import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useId, useState } from "react";
import { Bot, CheckCircle2, Circle, Info } from "lucide-react";
import { AgentActivitySidebar } from "@/components/agent-activity-sidebar";
import { ExperimentalBadge } from "@/components/experimental-badge";
import { ResultView } from "@/components/result-view";
import { WorkflowForm } from "@/components/workflow-form";
import { WorkflowJobHistory } from "@/components/workflow-job-history";
import { api } from "@/lib/api";
import type { Job, UseCaseContract, Workflow } from "@/lib/types";
import { workflowById, type WorkflowDefinition } from "@/lib/workflows";
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
      <WorkflowHero definition={definition} workspaceLabel={workspaceLabel} executionSteps={executionSteps} contract={contract.data} jobStatus={jobQuery.data?.status} hasJob={Boolean(jobId)} />
      <div className={`mt-7 grid items-start gap-7 xl:grid-cols-[260px_minmax(0,1fr)] ${agentHistoryOpen ? "2xl:grid-cols-[240px_minmax(0,1fr)_380px]" : ""}`}>
        <aside>
          <WorkflowJobHistory workflow={workflow} currentJobId={jobId} discipline={discipline} />
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

function WorkflowHero({ definition, workspaceLabel, executionSteps, contract, jobStatus, hasJob }: { definition: WorkflowDefinition; workspaceLabel: string; executionSteps: string[]; contract?: UseCaseContract; jobStatus?: Job["status"]; hasJob: boolean }) {
  const tooltipId = useId();
  const Icon = definition.icon;
  return (
    <header className="rounded-2xl border border-white/10 bg-[linear-gradient(125deg,rgba(124,58,237,0.11),rgba(24,24,27,0.96)_34%,rgba(24,24,27,0.96))] p-5 shadow-sm lg:p-6">
      <div className="flex items-center justify-between gap-4">
        <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-zinc-500">{workspaceLabel} / {definition.shortTitle}</p>
        <Link href="/" className="focus-ring text-xs font-medium text-zinc-500 transition hover:text-white">All modules</Link>
      </div>
      <div className="mt-4 flex items-start gap-4 sm:items-center">
        <div className="grid h-12 w-12 shrink-0 place-items-center rounded-xl border border-violet-400/20 bg-violet-500/15 text-violet-300"><Icon size={22} /></div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-[10px] font-black uppercase tracking-[0.16em] text-violet-300">{definition.eyebrow}</p>
            <span className="inline-flex items-center gap-1 rounded-full border border-white/10 bg-white/[0.04] px-2 py-1 text-[9px] font-bold uppercase tracking-[0.08em] text-zinc-400"><Bot size={11} /> Specialist generation agent</span>
          </div>
          <div className="mt-1.5 flex flex-wrap items-center gap-3"><h1 className="text-2xl font-semibold tracking-[-0.025em] text-white sm:text-3xl">{definition.title}</h1>{definition.experimental && <ExperimentalBadge />}</div>
          <p className="mt-1.5 max-w-4xl text-xs leading-5 text-zinc-400 sm:text-sm sm:leading-6">{definition.description}</p>
        </div>
        <div className="group/contract relative hidden shrink-0 sm:block">
          <button type="button" aria-describedby={tooltipId} className="focus-ring inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-xs font-semibold text-zinc-300 transition hover:border-violet-400/30 hover:bg-violet-500/10 hover:text-white"><Info size={14} /> Contract</button>
          <div id={tooltipId} role="tooltip" className="pointer-events-none invisible absolute right-0 top-[calc(100%+0.5rem)] z-50 w-[min(24rem,calc(100vw-2.5rem))] translate-y-1 rounded-xl border border-violet-400/25 bg-[#111113] p-4 opacity-0 shadow-2xl transition duration-150 group-hover/contract:visible group-hover/contract:translate-y-0 group-hover/contract:opacity-100 group-focus-within/contract:visible group-focus-within/contract:translate-y-0 group-focus-within/contract:opacity-100">
        <p className="flex items-center gap-2 text-xs font-semibold text-zinc-100"><Info size={15} className="text-violet-300" /> Agent execution contract</p>
        <ol className="mt-3 space-y-2.5 text-xs text-zinc-500">{executionSteps.map((step, index) => <li key={step} className="flex items-start gap-2">{hasJob && (jobStatus === "succeeded" || index === 0) ? <CheckCircle2 size={14} className="mt-0.5 shrink-0 text-clinical-600" /> : <Circle size={14} className="mt-0.5 shrink-0 text-zinc-600" />}<span>{step}</span></li>)}</ol>

        <div className="mt-4 border-t border-white/10 pt-4">
          <p className="text-xs font-semibold text-zinc-100">Shared use-case contract</p>
          {contract ? <>
            <p className="mt-3 flex items-start gap-2 text-xs leading-5 text-zinc-400"><Bot size={14} className="mt-0.5 shrink-0 text-violet-300" /><span>Agent: <span className="font-semibold text-zinc-100">{contract.agent_name}</span><br /><span className="font-mono text-[11px] text-violet-300">{contract.agent_id}</span></span></p>
            <p className="mt-2 text-xs leading-5 text-zinc-400">Skill: <span className="font-mono text-violet-300">{contract.skill_name}</span></p>
            {contract.stages && contract.stages.length > 0 && <p className="mt-2 text-xs leading-5 text-zinc-400">Stages: {contract.stages.join(" → ")}</p>}
            <p className="mt-2 text-xs leading-5 text-zinc-400">Outputs: {contract.output_formats.join(", ").toUpperCase()}</p>
            <p className="mt-2 text-xs leading-5 text-zinc-400">Result editing: {contract.supports_result_editing ? "schema-validated" : "disabled"}</p>
          </> : <p className="mt-2 text-xs leading-5 text-zinc-500">Contract details are loading…</p>}
        </div>
      </div>
      </div>
      </div>
      <div className="group/contract relative mt-4 sm:hidden">
        <button type="button" aria-describedby={`${tooltipId}-mobile`} className="focus-ring inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-xs font-semibold text-zinc-300 transition hover:border-violet-400/30 hover:bg-violet-500/10 hover:text-white"><Info size={14} /> Contract</button>
        <div id={`${tooltipId}-mobile`} role="tooltip" className="pointer-events-none invisible absolute left-0 top-[calc(100%+0.5rem)] z-50 w-[min(24rem,calc(100vw-3rem))] translate-y-1 rounded-xl border border-violet-400/25 bg-[#111113] p-4 opacity-0 shadow-2xl transition duration-150 group-hover/contract:visible group-hover/contract:translate-y-0 group-hover/contract:opacity-100 group-focus-within/contract:visible group-focus-within/contract:translate-y-0 group-focus-within/contract:opacity-100">
          <p className="flex items-center gap-2 text-xs font-semibold text-zinc-100"><Info size={15} className="text-violet-300" /> Agent execution contract</p>
          <ol className="mt-3 space-y-2 text-xs text-zinc-500">{executionSteps.map((step, index) => <li key={step} className="flex items-start gap-2">{hasJob && (jobStatus === "succeeded" || index === 0) ? <CheckCircle2 size={14} className="mt-0.5 shrink-0 text-clinical-600" /> : <Circle size={14} className="mt-0.5 shrink-0 text-zinc-600" />}<span>{step}</span></li>)}</ol>
          {contract && <p className="mt-3 border-t border-white/10 pt-3 text-xs leading-5 text-zinc-400">Agent: <span className="font-semibold text-zinc-100">{contract.agent_name}</span><br />Outputs: {contract.output_formats.join(", ").toUpperCase()}</p>}
        </div>
      </div>
    </header>
  );
}
