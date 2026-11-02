"use client";

import { useEffect, useId, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleHelp, Hash, LoaderCircle, Maximize2, Mic, MicOff, Minimize2, PanelRightClose, PanelRightOpen, Send } from "lucide-react";
import { api } from "@/lib/api";
import { convertRecordingToWav } from "@/lib/audio";
import { useReviewDraft, type SDTMRevisionContext } from "@/lib/review-draft-context";
import type { Job, ReviewScope } from "@/lib/types";
import { AgentTurnTimeline } from "./agent-turn-timeline";
import { StatusBadge } from "./status-badge";

export function AgentActivitySidebar({ job, onOpenChange }: { job: Job; onOpenChange?: (open: boolean) => void }) {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [fullScreen, setFullScreen] = useState(false);
  const [message, setMessage] = useState("");
  const queryClient = useQueryClient();
  const { currentResult, sdtmRevisionContext, setCsdrgAgentDraft } = useReviewDraft();
  const query = useQuery({
    queryKey: ["agent-progress", job.id],
    queryFn: () => api.agentProgress(job.id),
    refetchInterval: job.status === "queued" || job.status === "running" ? 2_000 : false,
  });
  const feedbackMutation = useMutation({
    mutationFn: ({ feedback, scope }: { feedback: string; scope: ReviewScope }) => api.submitReviewFeedback(job.id, {
      message: feedback,
      scope,
      baseline_revision: job.result_revision!,
      current_result: currentResult ?? asRecord(job.result),
    }),
    onSuccess: (updated) => {
      setMessage("");
      queryClient.setQueryData(["job", job.id], updated);
      queryClient.invalidateQueries({ queryKey: ["agent-progress", job.id] });
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
  });
  const completedRevisionMutation = useMutation({
    mutationFn: async ({ feedback, scope }: { feedback: string; scope: ReviewScope }) => {
      const context = sdtmRevisionContext;
      if (!context) throw new Error("Select an SDTM review tab before requesting a revision.");
      if (context.surface === "csdrg") {
        const document = await api.reviseCsdrgWithAgent(job.id, feedback, scope);
        return { kind: "csdrg" as const, document };
      }
      if (context.surface === "domain_mapping") {
        const updated = await api.rerunSdtmDomain(job.id, "domain_mapping", undefined, { guidance: feedback, scope });
        return { kind: "job" as const, job: updated };
      }
      if (!context.domain) throw new Error("Select a target domain before requesting this revision.");
      const stage = context.surface === "rule_augmentation" || context.surface === "execution"
        ? "rule_augmentation" as const
        : "variable_mapping" as const;
      const prefix = context.surface === "acrf"
        ? "aCRF metadata revision"
        : context.surface === "define_xml"
          ? "Define-XML source metadata revision"
          : context.surface === "execution"
            ? "Execution-informed rule/code revision"
            : context.surface === "rule_augmentation"
              ? "Rule/code revision"
              : "Variable/VLM revision";
      const updated = await api.rerunSdtmDomain(job.id, stage, context.domain, {
        guidance: `${prefix}: ${feedback}`,
        executionAttemptId: context.executionAttemptId,
        scope,
      });
      return { kind: "job" as const, job: updated };
    },
    onSuccess: (result) => {
      setMessage("");
      if (result.kind === "csdrg") {
        setCsdrgAgentDraft(result.document);
        return;
      }
      queryClient.setQueryData(["job", job.id], result.job);
      queryClient.invalidateQueries({ queryKey: ["agent-progress", job.id] });
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
  });

  useEffect(() => {
    setDrawerOpen(false);
    setFullScreen(false);
    onOpenChange?.(false);
  }, [job.id, onOpenChange]);

  useEffect(() => {
    if (job.status === "succeeded") setMessage("");
  }, [job.status, sdtmRevisionContext?.domain, sdtmRevisionContext?.executionAttemptId, sdtmRevisionContext?.surface]);

  const updateDrawerOpen = (open: boolean) => {
    setDrawerOpen(open);
    onOpenChange?.(open);
  };

  useEffect(() => {
    if (!drawerOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (fullScreen) setFullScreen(false);
      else updateDrawerOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [drawerOpen, fullScreen, onOpenChange]);

  const content = query.data
    ? <AgentTurnTimeline progress={query.data} result={job.result} warnings={job.warnings} compact={!fullScreen} />
    : <div className="grid min-h-48 place-items-center rounded-lg border border-dashed border-white/15 px-4 text-center text-xs leading-5 text-zinc-500">
        {query.isError ? `Agent trace unavailable: ${query.error.message}` : "Loading agent activity…"}
      </div>;
  const composer = job.status === "review_required" && !job.review_patch ? (
      <FeedbackComposer
        job={job}
        currentResult={currentResult ?? asRecord(job.result)}
        message={message}
        onMessageChange={setMessage}
        onSubmit={(scope) => feedbackMutation.mutate({ feedback: message.trim(), scope })}
        submitting={feedbackMutation.isPending}
        error={feedbackMutation.error?.message}
      />
    ) : job.status === "succeeded" && job.workflow === "sdtm" && sdtmRevisionContext ? (
      <CompletedSDTMRevisionComposer
        job={job}
        currentResult={currentResult ?? asRecord(job.result)}
        context={sdtmRevisionContext}
        message={message}
        onMessageChange={setMessage}
        onSubmit={(scope) => completedRevisionMutation.mutate({ feedback: message.trim(), scope })}
        submitting={completedRevisionMutation.isPending}
        error={completedRevisionMutation.error?.message}
        producesDraft={sdtmRevisionContext.surface === "csdrg"}
      />
    ) : null;

  return (
    <>
      {!drawerOpen && (
        <button
          type="button"
          onClick={() => updateDrawerOpen(true)}
          aria-expanded={false}
          className="focus-ring fixed bottom-5 right-5 z-40 inline-flex items-center gap-2 rounded-full border border-violet-400/30 bg-violet-600 px-4 py-3 text-sm font-bold text-white shadow-2xl transition hover:bg-violet-500"
        >
          <PanelRightOpen size={17} /> Agent history
        </button>
      )}

      {drawerOpen && (
        <>
          {!fullScreen && <button type="button" aria-label="Dismiss agent history overlay" onClick={() => updateDrawerOpen(false)} className="fixed inset-0 z-40 bg-black/70 backdrop-blur-sm 2xl:hidden" />}
          <aside
            role={fullScreen ? "dialog" : "complementary"}
            aria-modal={fullScreen ? true : undefined}
            aria-label="Agent activity history"
            className={fullScreen
              ? "fixed inset-0 z-50 flex flex-col bg-[#18181b]"
              : "fixed inset-y-0 right-0 z-50 flex w-[min(94vw,32rem)] flex-col border-l border-white/10 bg-[#18181b] shadow-2xl 2xl:sticky 2xl:top-4 2xl:z-auto 2xl:h-[calc(100vh-2rem)] 2xl:w-auto 2xl:rounded-xl 2xl:border 2xl:shadow-sm"}
          >
            <div className="flex items-start justify-between gap-3 border-b border-white/[0.08]">
              <ActivityHeader job={job} turnCount={query.data?.events.length} />
              <div className="mr-3 mt-3 flex shrink-0 items-center gap-2">
                <button type="button" onClick={() => setFullScreen((value) => !value)} className="focus-ring grid h-9 w-9 place-items-center rounded-lg border border-white/10 text-zinc-400 transition hover:bg-white/[0.06] hover:text-white" aria-label={fullScreen ? "Exit full screen agent history" : "View agent history full screen"} aria-pressed={fullScreen}>
                  {fullScreen ? <Minimize2 size={17} /> : <Maximize2 size={17} />}
                </button>
                <button type="button" onClick={() => { updateDrawerOpen(false); setFullScreen(false); }} className="focus-ring grid h-9 w-9 place-items-center rounded-lg border border-white/10 text-zinc-400 transition hover:bg-white/[0.06] hover:text-white" aria-label="Collapse agent history">
                  <PanelRightClose size={18} />
                </button>
              </div>
            </div>
            <div className={fullScreen ? "min-h-0 flex-1 overflow-y-auto p-5 lg:p-8" : "min-h-0 flex-1 overflow-y-auto p-3"}>{content}</div>
            {composer}
          </aside>
        </>
      )}
    </>
  );
}

function CompletedSDTMRevisionComposer({ job, currentResult, context, message, onMessageChange, onSubmit, submitting, error, producesDraft }: {
  job: Job;
  currentResult: Record<string, unknown>;
  context: SDTMRevisionContext;
  message: string;
  onMessageChange: (value: string) => void;
  onSubmit: (scope: ReviewScope) => void;
  submitting: boolean;
  error?: string;
  producesDraft: boolean;
}) {
  const [scope, setScope] = useState<ReviewScope>(() => completedRevisionScope(context));
  useEffect(() => setScope(completedRevisionScope(context)), [context.domain, context.surface, context.variable]);
  const hasScope = scope.paths.length > 0 || scope.source_datasets.length > 0 || scope.target_domains.length > 0 || scope.variables.length > 0;
  const canSubmit = Boolean(message.trim()) && hasScope && !submitting;
  const help = `Revise ${context.label}. The active tab and selected domain determine the agent and initial scope. ${producesDraft ? "The draft will open in the existing editor for review and saving." : "Approved artifacts remain active until you accept the proposal."}`;
  return <form className="border-t border-white/[0.08] bg-[#151518] p-2.5" onSubmit={(event) => { event.preventDefault(); if (canSubmit) onSubmit(scope); }}>
    <div className="flex items-center gap-1.5">
      <p className="min-w-0 flex-1 truncate text-[11px] font-bold text-zinc-200">{context.label}</p>
      <InfoTooltip label="About this revision" description={help} />
    </div>
    <textarea
      aria-label="Review guidance for the agent"
      value={message}
      onChange={(event) => onMessageChange(event.target.value.slice(0, 4000))}
      rows={2}
      maxLength={4000}
      placeholder="Describe the requested change…"
      className="focus-ring mt-1.5 w-full resize-y rounded-lg border border-white/10 bg-[#0d0d0f] px-3 py-2 text-xs leading-5 text-zinc-200 placeholder:text-zinc-600"
    />
    <div className="mt-1.5 flex items-center gap-1.5">
      <VoiceGuidanceInput jobId={job.id} message={message} onMessageChange={onMessageChange} submitting={submitting} />
      <ScopeMenu hasScope={hasScope} summary={scopeSummary(scope)}>
        <CompletedRevisionScopePicker context={context} currentResult={currentResult} scope={scope} onChange={setScope} />
      </ScopeMenu>
      <span className="ml-1 text-[9px] tabular-nums text-zinc-600">{message.length}/4000</span>
      <span className="flex-1" />
      <button type="submit" disabled={!canSubmit} className="focus-ring inline-flex items-center gap-1.5 rounded-lg bg-violet-600 px-3 py-2 text-xs font-bold text-white transition hover:bg-violet-500 disabled:cursor-not-allowed disabled:opacity-40">
        {submitting ? <LoaderCircle size={14} className="animate-spin" /> : <Send size={14} />}
        {submitting ? "Agent is revising…" : producesDraft ? "Draft revision" : "Generate proposal"}
      </button>
    </div>
    {error && <p className="mt-2 rounded-md border border-rose-500/20 bg-rose-500/10 px-2.5 py-2 text-[11px] leading-4 text-rose-300">{error}</p>}
  </form>;
}

function completedRevisionScope(context: SDTMRevisionContext): ReviewScope {
  if (context.surface === "domain_mapping") return { ...emptyScope(), paths: ["/domain_mappings", "/unmapped_datasets", "/datasets", "/rule_augmentations", "/assumptions", "/unresolved_mappings"] };
  if (context.surface === "csdrg") return { ...emptyScope(), paths: ["/sections"] };
  if (context.domain && context.variable) return { ...emptyScope(), variables: [{ domain: context.domain, variable: context.variable, fields: [] }] };
  if (context.domain) return { ...emptyScope(), target_domains: [context.domain] };
  return emptyScope();
}

function CompletedRevisionScopePicker({ context, currentResult, scope, onChange }: {
  context: SDTMRevisionContext;
  currentResult: Record<string, unknown>;
  scope: ReviewScope;
  onChange: (scope: ReviewScope) => void;
}) {
  if (context.surface === "domain_mapping") return <FixedScope label="Revision scope" value="Complete source-to-domain plan and dependent mappings/programs" />;
  if (context.surface === "csdrg") return <FixedScope label="Revision scope" value="Reviewer-editable cSDRG narrative; evidence-controlled sections stay locked" />;
  const domain = context.domain ?? "";
  const datasets = asRecords(currentResult.datasets);
  const dataset = datasets.find((item) => String(item.domain).toUpperCase() === domain.toUpperCase());
  const variables = asRecords(dataset?.variables);
  const selectedVariable = scope.variables[0]?.variable ?? "";
  const selectedFields = scope.variables[0]?.fields ?? [];
  const fieldLockAvailable = context.surface === "variable_mapping" || context.surface === "acrf" || context.surface === "define_xml";
  return <div className="grid gap-2">
    <div><p className="text-[10px] font-bold text-zinc-400">Affected target domain</p><p className="mt-1 rounded-md border border-violet-400/20 bg-violet-500/[0.08] px-2 py-1.5 font-mono text-[11px] font-bold text-violet-200">{domain}</p></div>
    {variables.length > 0 && <label className="text-[10px] font-bold text-zinc-400">Narrow to one variable<select aria-label="Affected target variable" value={selectedVariable} onChange={(event) => onChange(event.target.value ? { ...emptyScope(), variables: [{ domain, variable: event.target.value, fields: [] }] } : { ...emptyScope(), target_domains: [domain] })} className={scopeInput}><option value="">Entire {domain} domain</option>{variables.map((item) => <option key={String(item.name)}>{String(item.name)}</option>)}</select></label>}
    {selectedVariable && fieldLockAvailable && <div><p className="text-[10px] font-bold text-zinc-400">Optional field lock</p><div className="mt-1 flex max-h-24 flex-wrap gap-1 overflow-auto">{variableFields.map((field) => <label key={field} className="flex items-center gap-1 rounded border border-white/10 px-1.5 py-1 text-[9px] text-zinc-400"><input type="checkbox" checked={selectedFields.includes(field)} onChange={() => { const fields = selectedFields.includes(field) ? selectedFields.filter((item) => item !== field) : [...selectedFields, field]; onChange({ ...emptyScope(), variables: [{ domain, variable: selectedVariable, fields }] }); }} />{field}</label>)}</div><p className="mt-1 text-[9px] text-zinc-600">No checked fields means the full variable row and its dependent rule are in scope.</p></div>}
  </div>;
}

function FixedScope({ label, value }: { label: string; value: string }) {
  return <div><p className="text-[10px] font-bold text-zinc-400">{label}</p><p className="mt-1 text-[10px] leading-4 text-zinc-300">{value}</p></div>;
}

function VoiceGuidanceInput({ jobId, message, onMessageChange, submitting }: { jobId: string; message: string; onMessageChange: (value: string) => void; submitting: boolean }) {
  const tooltipId = useId();
  const [voiceSupported, setVoiceSupported] = useState(false);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const mountedRef = useRef(true);
  const messageRef = useRef(message);
  const [voiceState, setVoiceState] = useState<"idle" | "requesting" | "recording" | "transcribing">("idle");
  const [voiceError, setVoiceError] = useState<string>();
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  messageRef.current = message;

  useEffect(() => setVoiceSupported(typeof MediaRecorder !== "undefined" && Boolean(navigator.mediaDevices?.getUserMedia)), []);
  useEffect(() => {
    if (voiceState !== "recording") return;
    const interval = window.setInterval(() => setElapsedSeconds((value) => value + 1), 1000);
    const limit = window.setTimeout(() => {
      if (recorderRef.current?.state === "recording") recorderRef.current.stop();
      setVoiceState("transcribing");
    }, 180_000);
    return () => { window.clearInterval(interval); window.clearTimeout(limit); };
  }, [voiceState]);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      const recorder = recorderRef.current;
      if (recorder && recorder.state !== "inactive") { recorder.onstop = null; recorder.stop(); }
      streamRef.current?.getTracks().forEach((track) => track.stop());
    };
  }, []);

  const startVoiceInput = async () => {
    if (!voiceSupported) return;
    setVoiceError(undefined);
    setVoiceState("requesting");
    setElapsedSeconds(0);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (!mountedRef.current) { stream.getTracks().forEach((track) => track.stop()); return; }
      streamRef.current = stream;
      chunksRef.current = [];
      const preferredType = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"].find((type) => MediaRecorder.isTypeSupported(type));
      const recorder = preferredType ? new MediaRecorder(stream, { mimeType: preferredType }) : new MediaRecorder(stream);
      recorderRef.current = recorder;
      recorder.ondataavailable = (event) => { if (event.data.size) chunksRef.current.push(event.data); };
      recorder.onerror = () => {
        stream.getTracks().forEach((track) => track.stop());
        if (mountedRef.current) { setVoiceError("Microphone recording failed. Please try again."); setVoiceState("idle"); }
      };
      recorder.onstop = async () => {
        stream.getTracks().forEach((track) => track.stop());
        streamRef.current = null;
        if (!mountedRef.current) return;
        setVoiceState("transcribing");
        try {
          const recording = new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" });
          if (!recording.size) throw new Error("No microphone audio was captured.");
          const wav = await convertRecordingToWav(recording);
          const result = await api.transcribeReviewAudio(jobId, wav);
          const existing = messageRef.current.trimEnd();
          onMessageChange(`${existing}${existing ? "\n" : ""}${result.transcript}`.slice(0, 4000));
        } catch (caught) {
          setVoiceError(caught instanceof Error ? caught.message : "Voice transcription failed.");
        } finally {
          if (mountedRef.current) setVoiceState("idle");
        }
      };
      recorder.start(250);
      setVoiceState("recording");
    } catch (caught) {
      const denied = caught instanceof DOMException && caught.name === "NotAllowedError";
      setVoiceError(denied ? "Microphone access was denied. Allow access in the browser and try again." : "The microphone could not be started.");
      setVoiceState("idle");
    }
  };
  const stopVoiceInput = () => {
    if (recorderRef.current?.state === "recording") recorderRef.current.stop();
    setVoiceState("transcribing");
  };
  const minutes = Math.floor(elapsedSeconds / 60);
  const seconds = String(elapsedSeconds % 60).padStart(2, "0");
  return <>
    <div className="group/voice relative">
      <button type="button" onClick={voiceState === "recording" ? stopVoiceInput : startVoiceInput} disabled={!voiceSupported || voiceState === "requesting" || voiceState === "transcribing" || submitting} aria-label={voiceState === "recording" ? "Stop voice input" : "Start voice input"} aria-describedby={tooltipId} aria-pressed={voiceState === "recording"} className={`focus-ring grid h-8 min-w-8 place-items-center rounded-lg border px-2 text-[10px] font-bold transition disabled:cursor-not-allowed disabled:opacity-40 ${voiceState === "recording" ? "border-rose-400/40 bg-rose-500/15 text-rose-200" : "border-white/10 bg-white/[0.04] text-zinc-300 hover:bg-white/[0.08]"}`}>
        {voiceState === "requesting" || voiceState === "transcribing" ? <LoaderCircle size={14} className="animate-spin" /> : voiceState === "recording" ? <MicOff size={14} /> : <Mic size={14} />}
        {voiceState === "recording" && <span className="ml-1">{minutes}:{seconds}</span>}
      </button>
      <div id={tooltipId} role="tooltip" className={`pointer-events-none absolute bottom-[calc(100%+0.5rem)] left-0 z-50 w-64 rounded-lg border bg-[#101012] p-2.5 text-[10px] font-normal leading-4 shadow-2xl transition ${voiceError ? "visible translate-y-0 border-rose-500/25 text-rose-300 opacity-100" : "invisible translate-y-1 border-white/15 text-zinc-300 opacity-0 group-hover/voice:visible group-hover/voice:translate-y-0 group-hover/voice:opacity-100 group-focus-within/voice:visible group-focus-within/voice:translate-y-0 group-focus-within/voice:opacity-100"}`}>
        {voiceError ?? (voiceSupported ? "Record synthetic or de-identified guidance. Meta Muse adds editable text and never submits it automatically. Audio is not stored by this workbench." : "Voice input is unavailable in this browser.")}
      </div>
    </div>
  </>;
}

function FeedbackComposer({ job, currentResult, message, onMessageChange, onSubmit, submitting, error }: { job: Job; currentResult: Record<string, unknown>; message: string; onMessageChange: (value: string) => void; onSubmit: (scope: ReviewScope) => void; submitting: boolean; error?: string }) {
  const stage = job.review_stage ? REVIEW_STAGE_LABELS[job.review_stage] : "current stage";
  const [scope, setScope] = useState<ReviewScope>(emptyScope);
  const scopeMutation = useMutation({
    mutationFn: () => api.proposeReviewScope(job.id, message.trim(), currentResult),
    onSuccess: (proposal) => setScope(proposal.scope),
  });
  const hasScope = scope.paths.length > 0 || scope.source_datasets.length > 0 || scope.target_domains.length > 0 || scope.variables.length > 0;
  const canSubmit = Boolean(message.trim()) && hasScope && Boolean(job.result_revision) && !submitting;

  useEffect(() => { if (!message) setScope(emptyScope()); }, [message]);
  return (
    <form
      className="border-t border-white/[0.08] bg-[#151518] p-2.5"
      onSubmit={(event) => { event.preventDefault(); if (canSubmit) onSubmit(scope); }}
    >
      <div className="flex items-center gap-1.5">
        <p className="min-w-0 flex-1 truncate text-[11px] font-bold text-zinc-200">Revise {stage}</p>
        <InfoTooltip label="About this revision" description={`Ask the agent to revise ${stage}. Generating a patch does not approve it or advance the workflow.`} />
      </div>
      <textarea
        aria-label="Review guidance for the agent"
        value={message}
        onChange={(event) => onMessageChange(event.target.value.slice(0, 4000))}
        rows={2}
        maxLength={4000}
        placeholder="Describe the requested change…"
        className="focus-ring mt-1.5 w-full resize-y rounded-lg border border-white/10 bg-[#0d0d0f] px-3 py-2 text-xs leading-5 text-zinc-200 placeholder:text-zinc-600"
      />
      <div className="mt-1.5 flex items-center gap-1.5">
        <VoiceGuidanceInput jobId={job.id} message={message} onMessageChange={onMessageChange} submitting={submitting} />
        <ScopeMenu
          hasScope={hasScope}
          summary={scopeSummary(scope)}
          suggestScope={{ disabled: !message.trim() || scopeMutation.isPending, pending: scopeMutation.isPending, onClick: () => scopeMutation.mutate() }}
          proposalNote={scopeMutation.data ? `${scopeMutation.data.explanation} Confirm or adjust the selection.` : undefined}
          proposalError={scopeMutation.error?.message}
        >
          <ScopePicker job={job} currentResult={currentResult} scope={scope} onChange={setScope} />
        </ScopeMenu>
        <span className="ml-1 text-[9px] tabular-nums text-zinc-600">{message.length}/4000</span>
        <span className="flex-1" />
        <button type="submit" disabled={!canSubmit} className="focus-ring inline-flex items-center gap-1.5 rounded-lg bg-violet-600 px-3 py-2 text-xs font-bold text-white transition hover:bg-violet-500 disabled:cursor-not-allowed disabled:opacity-40">
          {submitting ? <LoaderCircle size={14} className="animate-spin" /> : <Send size={14} />}
          {submitting ? "Generating scoped patch…" : "Generate patch"}
        </button>
      </div>
      {error && <p className="mt-2 rounded-md border border-rose-500/20 bg-rose-500/10 px-2.5 py-2 text-[11px] leading-4 text-rose-300">{error}</p>}
    </form>
  );
}

function InfoTooltip({ label, description }: { label: string; description: string }) {
  const tooltipId = useId();
  return <div className="group/info relative shrink-0">
    <button type="button" aria-label={label} aria-describedby={tooltipId} className="focus-ring grid h-7 w-7 place-items-center rounded-md text-zinc-500 transition hover:bg-white/[0.06] hover:text-zinc-200">
      <CircleHelp size={14} />
    </button>
    <div id={tooltipId} role="tooltip" className="pointer-events-none invisible absolute bottom-[calc(100%+0.4rem)] right-0 z-50 w-72 translate-y-1 rounded-lg border border-white/15 bg-[#101012] p-2.5 text-[10px] font-normal leading-4 text-zinc-300 opacity-0 shadow-2xl transition group-hover/info:visible group-hover/info:translate-y-0 group-hover/info:opacity-100 group-focus-within/info:visible group-focus-within/info:translate-y-0 group-focus-within/info:opacity-100">
      {description}
    </div>
  </div>;
}

function ScopeMenu({ hasScope, summary, children, suggestScope, proposalNote, proposalError }: {
  hasScope: boolean;
  summary: string;
  children: React.ReactNode;
  suggestScope?: { disabled: boolean; pending: boolean; onClick: () => void };
  proposalNote?: string;
  proposalError?: string;
}) {
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const menuId = useId();
  const tooltipId = useId();
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === "Escape") setOpen(false); };
    window.addEventListener("pointerdown", onPointerDown);
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("pointerdown", onPointerDown);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);
  return <div ref={menuRef} className="group/scope relative">
    <button
      type="button"
      aria-label="Select revision scope"
      aria-describedby={tooltipId}
      aria-expanded={open}
      aria-controls={menuId}
      onClick={() => setOpen((value) => !value)}
      className={`focus-ring relative grid h-8 w-8 place-items-center rounded-lg border transition ${open ? "border-violet-400/50 bg-violet-500/15 text-violet-200" : hasScope ? "border-emerald-400/25 bg-emerald-500/[0.08] text-emerald-300 hover:bg-emerald-500/15" : "border-amber-400/25 bg-amber-500/[0.08] text-amber-300 hover:bg-amber-500/15"}`}
    >
      <Hash size={15} />
      <span className={`absolute right-1 top-1 h-1.5 w-1.5 rounded-full ${hasScope ? "bg-emerald-400" : "bg-amber-400"}`} />
    </button>
    {!open && <div id={tooltipId} role="tooltip" className="pointer-events-none invisible absolute bottom-[calc(100%+0.5rem)] left-0 z-50 w-56 translate-y-1 rounded-lg border border-white/15 bg-[#101012] p-2.5 text-[10px] font-normal leading-4 text-zinc-300 opacity-0 shadow-2xl transition group-hover/scope:visible group-hover/scope:translate-y-0 group-hover/scope:opacity-100 group-focus-within/scope:visible group-focus-within/scope:translate-y-0 group-focus-within/scope:opacity-100">
      {hasScope ? `Scope: ${summary}. Select to review or change it.` : "Select the revision scope before submitting."}
    </div>}
    {open && <div id={menuId} role="dialog" aria-label="Revision scope" className="absolute -left-10 bottom-[calc(100%+0.5rem)] z-50 max-h-[min(28rem,70vh)] w-[min(28rem,calc(100vw-2rem))] overflow-y-auto rounded-xl border border-white/15 bg-[#101012] p-3 shadow-2xl">
      <div className="mb-2 flex items-center justify-between gap-3">
        <div><p className="text-[10px] font-black uppercase tracking-[0.12em] text-violet-300">Revision scope</p><p className={`mt-0.5 text-[9px] ${hasScope ? "text-emerald-300" : "text-amber-300"}`}>{hasScope ? summary : "No scope selected"}</p></div>
        {suggestScope && <button type="button" disabled={suggestScope.disabled} onClick={suggestScope.onClick} className="focus-ring rounded-md border border-white/10 px-2 py-1.5 text-[9px] font-bold text-zinc-300 transition hover:bg-white/[0.06] disabled:opacity-40">{suggestScope.pending ? "Finding…" : "Suggest from guidance"}</button>}
      </div>
      {children}
      {proposalNote && <p className="mt-2 text-[9px] leading-4 text-zinc-500">{proposalNote}</p>}
      {proposalError && <p className="mt-2 text-[9px] text-rose-300">{proposalError}</p>}
    </div>}
  </div>;
}

function scopeSummary(scope: ReviewScope): string {
  const variable = scope.variables[0];
  if (variable) return `${variable.domain}.${variable.variable}${variable.fields.length ? ` · ${variable.fields.length} fields` : ""}`;
  if (scope.target_domains.length) return scope.target_domains.join(", ");
  if (scope.source_datasets.length) return `${scope.source_datasets.length} source dataset${scope.source_datasets.length === 1 ? "" : "s"}`;
  if (scope.paths.length) return `${scope.paths.length} section${scope.paths.length === 1 ? "" : "s"}`;
  return "not selected";
}

const variableFields = ["label", "data_type", "mapping_type", "sources", "origin", "mapping_expression", "controlled_terms", "value_level_metadata", "crf_source_label", "acrf_annotations"];

function ScopePicker({ job, currentResult, scope, onChange }: { job: Job; currentResult: Record<string, unknown>; scope: ReviewScope; onChange: (value: ReviewScope) => void }) {
  if (job.workflow === "sdtm" && job.review_stage === "domain_mapping") {
    const sourceSpec = asRecord(currentResult.source_spec);
    const datasets = asRecords(sourceSpec.datasets);
    return <ScopeChecklist label="Affected source datasets" items={datasets.map((item) => String(item.name ?? "")).filter(Boolean)} selected={scope.source_datasets} onChange={(source_datasets) => onChange({ ...emptyScope(), source_datasets })} />;
  }
  if (job.workflow === "sdtm" && job.review_stage === "variable_mapping") {
    const plan = asRecord(currentResult.variable_mapping);
    const datasets = asRecords(plan.datasets);
    const selectedDomain = scope.variables[0]?.domain ?? scope.target_domains[0] ?? "";
    const dataset = datasets.find((item) => String(item.domain).toUpperCase() === selectedDomain);
    const variables = asRecords(dataset?.variables);
    const selectedVariable = scope.variables[0]?.variable ?? "";
    const selectedFields = scope.variables[0]?.fields ?? [];
    return <div className="grid gap-2">
      <label className="text-[10px] font-bold text-zinc-400">Affected target domain<select aria-label="Affected target domain" value={selectedDomain} onChange={(event) => onChange({ ...emptyScope(), target_domains: event.target.value ? [event.target.value] : [] })} className={scopeInput}><option value="">Select domain</option>{datasets.map((item) => <option key={String(item.domain)}>{String(item.domain)}</option>)}</select></label>
      {selectedDomain && <label className="text-[10px] font-bold text-zinc-400">Narrow to one variable<select aria-label="Affected target variable" value={selectedVariable} onChange={(event) => onChange(event.target.value ? { ...emptyScope(), variables: [{ domain: selectedDomain, variable: event.target.value, fields: [] }] } : { ...emptyScope(), target_domains: [selectedDomain] })} className={scopeInput}><option value="">Entire {selectedDomain} domain</option>{variables.map((item) => <option key={String(item.name)}>{String(item.name)}</option>)}</select></label>}
      {selectedVariable && <div><p className="text-[10px] font-bold text-zinc-400">Optional field lock</p><div className="mt-1 flex max-h-24 flex-wrap gap-1 overflow-auto">{variableFields.map((field) => <label key={field} className="flex items-center gap-1 rounded border border-white/10 px-1.5 py-1 text-[9px] text-zinc-400"><input type="checkbox" checked={selectedFields.includes(field)} onChange={() => { const fields = selectedFields.includes(field) ? selectedFields.filter((item) => item !== field) : [...selectedFields, field]; onChange({ ...emptyScope(), variables: [{ domain: selectedDomain, variable: selectedVariable, fields }] }); }} />{field}</label>)}</div><p className="mt-1 text-[9px] text-zinc-600">No checked fields means the full variable row is in scope.</p></div>}
    </div>;
  }
  const choices = genericPathChoices(job, currentResult);
  return <ScopeChecklist label="Affected draft sections" items={choices.map((item) => item.path)} labels={Object.fromEntries(choices.map((item) => [item.path, item.label]))} selected={scope.paths} onChange={(paths) => onChange({ ...emptyScope(), paths })} />;
}

function ScopeChecklist({ label, items, labels = {}, selected, onChange }: { label: string; items: string[]; labels?: Record<string, string>; selected: string[]; onChange: (items: string[]) => void }) {
  return <div><p className="text-[10px] font-bold text-zinc-400">{label}</p><div className="mt-1 max-h-28 space-y-1 overflow-auto">{items.map((item) => <label key={item} className="flex items-center gap-2 text-[10px] text-zinc-300"><input type="checkbox" checked={selected.includes(item)} onChange={() => onChange(selected.includes(item) ? selected.filter((value) => value !== item) : [...selected, item])} /><span>{labels[item] ?? item}</span></label>)}</div></div>;
}

function genericPathChoices(job: Job, current: Record<string, unknown>): Array<{ path: string; label: string }> {
  const choices: Array<{ path: string; label: string }> = [];
  collectPathChoices(current, "", "", choices, 0);
  return choices.slice(0, 200);
}

function collectPathChoices(value: unknown, path: string, label: string, choices: Array<{ path: string; label: string }>, depth: number) {
  if (choices.length >= 200 || depth > 5) return;
  if (Array.isArray(value)) {
    if (!value.length || !value.every((item) => item && typeof item === "object" && !Array.isArray(item))) {
      if (path) choices.push({ path, label });
      return;
    }
    value.forEach((item, index) => {
      const record = asRecord(item);
      const selector = entitySelector(record, index);
      const itemPath = `${path}/${selector}`;
      const itemLabel = `${label} · ${entityLabel(record, index)}`;
      choices.push({ path: itemPath, label: `${itemLabel} (entire item)` });
      collectPathChoices(record, itemPath, itemLabel, choices, depth + 1);
    });
    return;
  }
  if (value && typeof value === "object") {
    for (const [key, child] of Object.entries(value as Record<string, unknown>)) {
      const childPath = `${path}/${escapePointer(key)}`;
      const childLabel = label ? `${label} · ${key.replaceAll("_", " ")}` : key.replaceAll("_", " ");
      if (child && typeof child === "object") collectPathChoices(child, childPath, childLabel, choices, depth + 1);
      else choices.push({ path: childPath, label: childLabel });
    }
  }
}

function emptyScope(): ReviewScope { return { paths: [], source_datasets: [], target_domains: [], variables: [] }; }
function asRecord(value: unknown): Record<string, unknown> { return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {}; }
function asRecords(value: unknown): Record<string, unknown>[] { return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item)) : []; }
function entityLabel(item: Record<string, unknown>, index: number): string { return String(item.output_id ?? item.domain ?? item.name ?? item.title ?? index + 1); }
function entitySelector(item: Record<string, unknown>, index: number): string {
  for (const key of ["output_id", "domain", "name", "source_dataset", "variable", "finding_id", "where_clause"]) {
    if (item[key] !== undefined && item[key] !== null && String(item[key])) return `${key}=${escapePointer(String(item[key]))}`;
  }
  return String(index);
}
function escapePointer(value: string): string { return value.replaceAll("~", "~0").replaceAll("/", "~1"); }
const scopeInput = "mt-1 w-full rounded-md border border-white/10 bg-[#0d0d0f] px-2 py-1.5 text-[11px] text-zinc-200";

const REVIEW_STAGE_LABELS: Record<NonNullable<Job["review_stage"]>, string> = {
  edc_source: "EDC source specification",
  domain_mapping: "SDTM domain mapping",
  domain_mapping_completed: "Completed SDTM domain-mapping rerun",
  variable_mapping: "SDTM variable and value-level mapping",
  variable_mapping_domain: "Completed SDTM domain variable/VLM rerun",
  rule_augmentation_domain: "Completed SDTM domain rule rerun",
  tlf_inventory: "TLF output inventory",
  tlf_shell: "TLF shell",
  tlf_programming: "TLF programming plan",
};

function ActivityHeader({ job, turnCount }: { job: Job; turnCount?: number }) {
  return (
    <div className="min-w-0 flex-1 px-4 py-4">
      <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-zinc-500">Agent activity</p>
      <div className="mt-1 flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold text-zinc-100">Turns <span className="font-normal text-zinc-500">({turnCount ?? 0})</span></h2>
        <StatusBadge status={job.status} compact />
      </div>
    </div>
  );
}
