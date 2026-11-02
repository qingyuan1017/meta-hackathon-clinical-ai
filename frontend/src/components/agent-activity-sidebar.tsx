"use client";

import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { LoaderCircle, Maximize2, Mic, MicOff, Minimize2, PanelRightClose, PanelRightOpen, Send } from "lucide-react";
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
    : <div className="grid min-h-48 place-items-center rounded-lg border border-dashed border-slate-300 px-4 text-center text-xs leading-5 text-slate-500">
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
          className="focus-ring fixed bottom-5 right-5 z-40 inline-flex items-center gap-2 rounded-full border border-teal-400/30 bg-teal-600 px-4 py-3 text-sm font-bold text-white shadow-2xl transition hover:bg-teal-500"
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
              ? "fixed inset-0 z-50 flex flex-col bg-white"
              : "fixed inset-y-0 right-0 z-50 flex w-[min(94vw,32rem)] flex-col border-l border-slate-200 bg-white shadow-2xl 2xl:sticky 2xl:top-4 2xl:z-auto 2xl:h-[calc(100vh-2rem)] 2xl:w-auto 2xl:rounded-xl 2xl:border 2xl:shadow-sm"}
          >
            <div className="flex items-start justify-between gap-3 border-b border-slate-200">
              <ActivityHeader job={job} turnCount={query.data?.events.length} />
              <div className="mr-3 mt-3 flex shrink-0 items-center gap-2">
                <button type="button" onClick={() => setFullScreen((value) => !value)} className="focus-ring grid h-9 w-9 place-items-center rounded-lg border border-slate-200 text-slate-600 transition hover:bg-slate-100 hover:text-slate-900" aria-label={fullScreen ? "Exit full screen agent history" : "View agent history full screen"} aria-pressed={fullScreen}>
                  {fullScreen ? <Minimize2 size={17} /> : <Maximize2 size={17} />}
                </button>
                <button type="button" onClick={() => { updateDrawerOpen(false); setFullScreen(false); }} className="focus-ring grid h-9 w-9 place-items-center rounded-lg border border-slate-200 text-slate-600 transition hover:bg-slate-100 hover:text-slate-900" aria-label="Collapse agent history">
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
  return <form className="border-t border-slate-200 bg-slate-50 p-3" onSubmit={(event) => { event.preventDefault(); if (canSubmit) onSubmit(scope); }}>
    <p className="text-[10px] font-black uppercase tracking-[0.14em] text-teal-700">Guide this revision</p>
    <p className="mt-1 text-xs font-bold text-slate-800">{context.label}</p>
    <p className="mt-1 text-[11px] leading-4 text-slate-500">The active tab and selected domain determine the agent and revision scope. Change the selection in the workspace to target something else.</p>
    <VoiceGuidanceInput jobId={job.id} message={message} onMessageChange={onMessageChange} submitting={submitting} />
    <textarea
      aria-label="Review guidance for the agent"
      value={message}
      onChange={(event) => onMessageChange(event.target.value.slice(0, 4000))}
      rows={4}
      maxLength={4000}
      placeholder="Describe the change for the current selection."
      className="focus-ring mt-2 w-full resize-y rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs leading-5 text-slate-800 placeholder:text-slate-400"
    />
    <CompletedRevisionScopePicker context={context} currentResult={currentResult} scope={scope} onChange={setScope} />
    <div className="mt-2 flex items-center justify-between gap-3">
      <span className={`text-[10px] ${hasScope ? "text-emerald-700" : "text-amber-800"}`}>{hasScope ? `Scope confirmed · ${message.length}/4000` : "Select a scope before submitting"}</span>
      <button type="submit" disabled={!canSubmit} className="focus-ring inline-flex items-center gap-1.5 rounded-lg bg-teal-600 px-3 py-2 text-xs font-bold text-white transition hover:bg-teal-500 disabled:cursor-not-allowed disabled:opacity-40">
        {submitting ? <LoaderCircle size={14} className="animate-spin" /> : <Send size={14} />}
        {submitting ? "Agent is revising…" : producesDraft ? "Draft revision" : "Generate proposal"}
      </button>
    </div>
    {error && <p className="mt-2 rounded-md border border-rose-500/20 bg-rose-500/10 px-2.5 py-2 text-[11px] leading-4 text-rose-700">{error}</p>}
    <p className="mt-2 text-[10px] leading-4 text-amber-200/70">{producesDraft ? "The cSDRG draft will appear in the existing editor for review and saving." : "Approved artifacts remain active until the proposal is accepted."}</p>
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
  return <div className="mt-2 grid gap-2 rounded-lg border border-slate-200 bg-slate-50 p-2">
    <div><p className="text-[10px] font-bold text-slate-600">Affected target domain</p><p className="mt-1 rounded-md border border-teal-400/20 bg-teal-500/[0.08] px-2 py-1.5 font-mono text-[11px] font-bold text-teal-800">{domain}</p></div>
    {variables.length > 0 && <label className="text-[10px] font-bold text-slate-600">Narrow to one variable<select aria-label="Affected target variable" value={selectedVariable} onChange={(event) => onChange(event.target.value ? { ...emptyScope(), variables: [{ domain, variable: event.target.value, fields: [] }] } : { ...emptyScope(), target_domains: [domain] })} className={scopeInput}><option value="">Entire {domain} domain</option>{variables.map((item) => <option key={String(item.name)}>{String(item.name)}</option>)}</select></label>}
    {selectedVariable && fieldLockAvailable && <div><p className="text-[10px] font-bold text-slate-600">Optional field lock</p><div className="mt-1 flex max-h-24 flex-wrap gap-1 overflow-auto">{variableFields.map((field) => <label key={field} className="flex items-center gap-1 rounded border border-slate-200 px-1.5 py-1 text-[9px] text-slate-600"><input type="checkbox" checked={selectedFields.includes(field)} onChange={() => { const fields = selectedFields.includes(field) ? selectedFields.filter((item) => item !== field) : [...selectedFields, field]; onChange({ ...emptyScope(), variables: [{ domain, variable: selectedVariable, fields }] }); }} />{field}</label>)}</div><p className="mt-1 text-[9px] text-slate-400">No checked fields means the full variable row and its dependent rule are in scope.</p></div>}
  </div>;
}

function FixedScope({ label, value }: { label: string; value: string }) {
  return <div className="mt-2 rounded-lg border border-slate-200 bg-slate-50 p-2"><p className="text-[10px] font-bold text-slate-600">{label}</p><p className="mt-1 text-[10px] leading-4 text-slate-700">{value}</p></div>;
}

function VoiceGuidanceInput({ jobId, message, onMessageChange, submitting }: { jobId: string; message: string; onMessageChange: (value: string) => void; submitting: boolean }) {
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
    <div className="mt-2 flex items-center gap-2">
      <button type="button" onClick={voiceState === "recording" ? stopVoiceInput : startVoiceInput} disabled={!voiceSupported || voiceState === "requesting" || voiceState === "transcribing" || submitting} aria-label={voiceState === "recording" ? "Stop voice input" : "Start voice input"} aria-pressed={voiceState === "recording"} className={`focus-ring inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-2 text-[11px] font-bold transition disabled:cursor-not-allowed disabled:opacity-40 ${voiceState === "recording" ? "border-rose-400/40 bg-rose-500/15 text-rose-200" : "border-slate-200 bg-slate-50 text-slate-700 hover:bg-slate-100"}`}>
        {voiceState === "requesting" || voiceState === "transcribing" ? <LoaderCircle size={14} className="animate-spin" /> : voiceState === "recording" ? <MicOff size={14} /> : <Mic size={14} />}
        {voiceState === "requesting" ? "Opening mic…" : voiceState === "transcribing" ? "Transcribing…" : voiceState === "recording" ? `Stop ${minutes}:${seconds}` : "Voice input"}
      </button>
      <span className="text-[10px] leading-4 text-slate-400">Meta Muse adds editable text; it never auto-submits.</span>
    </div>
    {!voiceSupported && <p className="mt-1.5 text-[10px] leading-4 text-amber-800/80">Voice input is unavailable in this browser.</p>}
    {voiceError && <p className="mt-2 rounded-md border border-rose-500/20 bg-rose-500/10 px-2.5 py-2 text-[11px] leading-4 text-rose-700">{voiceError}</p>}
    <p className="mt-2 text-[10px] leading-4 text-slate-400">Record synthetic or de-identified guidance only. Audio is sent to the configured Meta Model API and is not stored by this workbench.</p>
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
      className="border-t border-slate-200 bg-slate-50 p-3"
      onSubmit={(event) => { event.preventDefault(); if (canSubmit) onSubmit(scope); }}
    >
      <p className="text-[10px] font-black uppercase tracking-[0.14em] text-teal-700">Guide this revision</p>
      <p className="mt-1 text-[11px] leading-4 text-slate-500">Ask the agent to revise {stage}. This does not approve or advance the workflow.</p>
      <VoiceGuidanceInput jobId={job.id} message={message} onMessageChange={onMessageChange} submitting={submitting} />
      <textarea
        aria-label="Review guidance for the agent"
        value={message}
        onChange={(event) => onMessageChange(event.target.value.slice(0, 4000))}
        rows={3}
        maxLength={4000}
        placeholder="Example: Use the Safety population for every adverse-event output and keep unsupported decisions as TODOs."
        className="focus-ring mt-2 w-full resize-y rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs leading-5 text-slate-800 placeholder:text-slate-400"
      />
      <ScopePicker job={job} currentResult={currentResult} scope={scope} onChange={setScope} />
      <div className="mt-2 flex items-center justify-between gap-2">
        <button type="button" disabled={!message.trim() || scopeMutation.isPending} onClick={() => scopeMutation.mutate()} className="focus-ring rounded-md border border-slate-200 px-2.5 py-1.5 text-[10px] font-bold text-slate-700 disabled:opacity-40">{scopeMutation.isPending ? "Finding scope…" : "Suggest scope from comment"}</button>
        <span className={`text-[10px] ${hasScope ? "text-emerald-700" : "text-amber-800"}`}>{hasScope ? "Scope confirmed" : "Select a scope before submitting"}</span>
      </div>
      {scopeMutation.data && <p className="mt-1 text-[10px] leading-4 text-slate-500">{scopeMutation.data.explanation} Confirm or adjust the selection.</p>}
      {scopeMutation.error && <p className="mt-1 text-[10px] text-rose-700">{scopeMutation.error.message}</p>}
      <div className="mt-2 flex items-center justify-between gap-3">
        <span className="text-[10px] text-slate-400">{message.length}/4000</span>
        <button type="submit" disabled={!canSubmit} className="focus-ring inline-flex items-center gap-1.5 rounded-lg bg-teal-600 px-3 py-2 text-xs font-bold text-white transition hover:bg-teal-500 disabled:cursor-not-allowed disabled:opacity-40">
          {submitting ? <LoaderCircle size={14} className="animate-spin" /> : <Send size={14} />}
          {submitting ? "Generating scoped patch…" : "Generate patch"}
        </button>
      </div>
      {error && <p className="mt-2 rounded-md border border-rose-500/20 bg-rose-500/10 px-2.5 py-2 text-[11px] leading-4 text-rose-700">{error}</p>}
    </form>
  );
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
    return <div className="mt-2 grid gap-2 rounded-lg border border-slate-200 bg-slate-50 p-2">
      <label className="text-[10px] font-bold text-slate-600">Affected target domain<select aria-label="Affected target domain" value={selectedDomain} onChange={(event) => onChange({ ...emptyScope(), target_domains: event.target.value ? [event.target.value] : [] })} className={scopeInput}><option value="">Select domain</option>{datasets.map((item) => <option key={String(item.domain)}>{String(item.domain)}</option>)}</select></label>
      {selectedDomain && <label className="text-[10px] font-bold text-slate-600">Narrow to one variable<select aria-label="Affected target variable" value={selectedVariable} onChange={(event) => onChange(event.target.value ? { ...emptyScope(), variables: [{ domain: selectedDomain, variable: event.target.value, fields: [] }] } : { ...emptyScope(), target_domains: [selectedDomain] })} className={scopeInput}><option value="">Entire {selectedDomain} domain</option>{variables.map((item) => <option key={String(item.name)}>{String(item.name)}</option>)}</select></label>}
      {selectedVariable && <div><p className="text-[10px] font-bold text-slate-600">Optional field lock</p><div className="mt-1 flex max-h-24 flex-wrap gap-1 overflow-auto">{variableFields.map((field) => <label key={field} className="flex items-center gap-1 rounded border border-slate-200 px-1.5 py-1 text-[9px] text-slate-600"><input type="checkbox" checked={selectedFields.includes(field)} onChange={() => { const fields = selectedFields.includes(field) ? selectedFields.filter((item) => item !== field) : [...selectedFields, field]; onChange({ ...emptyScope(), variables: [{ domain: selectedDomain, variable: selectedVariable, fields }] }); }} />{field}</label>)}</div><p className="mt-1 text-[9px] text-slate-400">No checked fields means the full variable row is in scope.</p></div>}
    </div>;
  }
  const choices = genericPathChoices(job, currentResult);
  return <ScopeChecklist label="Affected draft sections" items={choices.map((item) => item.path)} labels={Object.fromEntries(choices.map((item) => [item.path, item.label]))} selected={scope.paths} onChange={(paths) => onChange({ ...emptyScope(), paths })} />;
}

function ScopeChecklist({ label, items, labels = {}, selected, onChange }: { label: string; items: string[]; labels?: Record<string, string>; selected: string[]; onChange: (items: string[]) => void }) {
  return <div className="mt-2 rounded-lg border border-slate-200 bg-slate-50 p-2"><p className="text-[10px] font-bold text-slate-600">{label}</p><div className="mt-1 max-h-28 space-y-1 overflow-auto">{items.map((item) => <label key={item} className="flex items-center gap-2 text-[10px] text-slate-700"><input type="checkbox" checked={selected.includes(item)} onChange={() => onChange(selected.includes(item) ? selected.filter((value) => value !== item) : [...selected, item])} /><span>{labels[item] ?? item}</span></label>)}</div></div>;
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
const scopeInput = "mt-1 w-full rounded-md border border-slate-200 bg-slate-50 px-2 py-1.5 text-[11px] text-slate-800";

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
      <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-slate-500">Agent activity</p>
      <div className="mt-1 flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold text-slate-900">Turns <span className="font-normal text-slate-500">({turnCount ?? 0})</span></h2>
        <StatusBadge status={job.status} compact />
      </div>
    </div>
  );
}
