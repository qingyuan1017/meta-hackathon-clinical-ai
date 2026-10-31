"use client";

import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { LoaderCircle, Mic, MicOff, PanelRightClose, PanelRightOpen, Send } from "lucide-react";
import { api } from "@/lib/api";
import { convertRecordingToWav } from "@/lib/audio";
import type { Job } from "@/lib/types";
import { AgentTurnTimeline } from "./agent-turn-timeline";
import { StatusBadge } from "./status-badge";

export function AgentActivitySidebar({ job }: { job: Job }) {
  const shouldStartOpen = job.status === "queued" || job.status === "running" || job.status === "review_required";
  const [drawerOpen, setDrawerOpen] = useState(shouldStartOpen);
  const [message, setMessage] = useState("");
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ["agent-progress", job.id],
    queryFn: () => api.agentProgress(job.id),
    refetchInterval: job.status === "queued" || job.status === "running" ? 2_000 : false,
  });
  const feedbackMutation = useMutation({
    mutationFn: (feedback: string) => api.submitReviewFeedback(job.id, feedback),
    onSuccess: (updated) => {
      setMessage("");
      queryClient.setQueryData(["job", job.id], updated);
      queryClient.invalidateQueries({ queryKey: ["agent-progress", job.id] });
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
  });

  useEffect(() => setDrawerOpen(shouldStartOpen), [job.id, shouldStartOpen]);

  const content = query.data
    ? <AgentTurnTimeline progress={query.data} result={job.result} warnings={job.warnings} compact />
    : <div className="grid min-h-48 place-items-center rounded-lg border border-dashed border-white/15 px-4 text-center text-xs leading-5 text-zinc-500">
        {query.isError ? `Agent trace unavailable: ${query.error.message}` : "Loading agent activity…"}
      </div>;
  const composer = job.status === "review_required" ? (
    <FeedbackComposer
      job={job}
      message={message}
      onMessageChange={setMessage}
      onSubmit={() => feedbackMutation.mutate(message.trim())}
      submitting={feedbackMutation.isPending}
      error={feedbackMutation.error?.message}
    />
  ) : null;

  return (
    <>
      <aside className="sticky top-4 hidden max-h-[calc(100vh-2rem)] min-w-0 overflow-hidden rounded-xl border border-white/10 bg-[#18181b] shadow-sm 2xl:flex 2xl:flex-col" aria-label="Agent activity">
        <div className="border-b border-white/[0.08]"><ActivityHeader job={job} turnCount={query.data?.events.length} /></div>
        <div className="min-h-0 flex-1 overflow-y-auto p-3">{content}</div>
        {composer}
      </aside>

      <button
        type="button"
        onClick={() => setDrawerOpen(true)}
        aria-expanded={drawerOpen}
        className="focus-ring fixed bottom-5 right-5 z-40 inline-flex items-center gap-2 rounded-full border border-violet-400/30 bg-violet-600 px-4 py-3 text-sm font-bold text-white shadow-2xl 2xl:hidden"
      >
        <PanelRightOpen size={17} /> Agent activity
      </button>

      {drawerOpen && (
        <div className="fixed inset-0 z-50 2xl:hidden" role="dialog" aria-modal="true" aria-label="Agent activity">
          <button type="button" aria-label="Dismiss agent activity overlay" onClick={() => setDrawerOpen(false)} className="absolute inset-0 bg-black/70 backdrop-blur-sm" />
          <aside className="absolute inset-y-0 right-0 flex w-[min(94vw,32rem)] flex-col border-l border-white/10 bg-[#18181b] shadow-2xl">
            <div className="flex items-start justify-between gap-3 border-b border-white/[0.08]">
              <ActivityHeader job={job} turnCount={query.data?.events.length} />
              <button type="button" onClick={() => setDrawerOpen(false)} className="focus-ring mr-3 mt-3 grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-white/10 text-zinc-400 transition hover:bg-white/[0.06] hover:text-white" aria-label="Close agent activity">
                <PanelRightClose size={18} />
              </button>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto p-3">{content}</div>
            {composer}
          </aside>
        </div>
      )}
    </>
  );
}

function FeedbackComposer({ job, message, onMessageChange, onSubmit, submitting, error }: { job: Job; message: string; onMessageChange: (value: string) => void; onSubmit: () => void; submitting: boolean; error?: string }) {
  const stage = job.review_stage ? REVIEW_STAGE_LABELS[job.review_stage] : "current stage";
  const canSubmit = Boolean(message.trim()) && !submitting;
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

  useEffect(() => {
    setVoiceSupported(typeof MediaRecorder !== "undefined" && Boolean(navigator.mediaDevices?.getUserMedia));
  }, []);

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
      if (recorder && recorder.state !== "inactive") {
        recorder.onstop = null;
        recorder.stop();
      }
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
      const preferredType = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"]
        .find((type) => MediaRecorder.isTypeSupported(type));
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
          const result = await api.transcribeReviewAudio(job.id, wav);
          const existing = messageRef.current.trimEnd();
          onMessageChange(`${existing}${existing ? "\n" : ""}${result.transcript}`.slice(0, 4000));
        } catch (caught) {
          const detail = caught instanceof Error ? caught.message : "Voice transcription failed.";
          setVoiceError(detail);
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
  return (
    <form
      className="border-t border-white/[0.08] bg-[#151518] p-3"
      onSubmit={(event) => { event.preventDefault(); if (canSubmit) onSubmit(); }}
    >
      <p className="text-[10px] font-black uppercase tracking-[0.14em] text-violet-300">Guide this revision</p>
      <p className="mt-1 text-[11px] leading-4 text-zinc-500">Ask the agent to revise {stage}. This does not approve or advance the workflow.</p>
      <div className="mt-2 flex items-center gap-2">
        <button
          type="button"
          onClick={voiceState === "recording" ? stopVoiceInput : startVoiceInput}
          disabled={!voiceSupported || voiceState === "requesting" || voiceState === "transcribing" || submitting}
          aria-label={voiceState === "recording" ? "Stop voice input" : "Start voice input"}
          aria-pressed={voiceState === "recording"}
          className={`focus-ring inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-2 text-[11px] font-bold transition disabled:cursor-not-allowed disabled:opacity-40 ${voiceState === "recording" ? "border-rose-400/40 bg-rose-500/15 text-rose-200" : "border-white/10 bg-white/[0.04] text-zinc-300 hover:bg-white/[0.08]"}`}
        >
          {voiceState === "requesting" || voiceState === "transcribing" ? <LoaderCircle size={14} className="animate-spin" /> : voiceState === "recording" ? <MicOff size={14} /> : <Mic size={14} />}
          {voiceState === "requesting" ? "Opening mic…" : voiceState === "transcribing" ? "Transcribing…" : voiceState === "recording" ? `Stop ${minutes}:${seconds}` : "Voice input"}
        </button>
        <span className="text-[10px] leading-4 text-zinc-600">Meta Muse adds editable text; it never auto-submits.</span>
      </div>
      {!voiceSupported && <p className="mt-1.5 text-[10px] leading-4 text-amber-300/80">Voice input is unavailable in this browser.</p>}
      <textarea
        aria-label="Review guidance for the agent"
        value={message}
        onChange={(event) => onMessageChange(event.target.value.slice(0, 4000))}
        rows={3}
        maxLength={4000}
        placeholder="Example: Use the Safety population for every adverse-event output and keep unsupported decisions as TODOs."
        className="focus-ring mt-2 w-full resize-y rounded-lg border border-white/10 bg-[#0d0d0f] px-3 py-2 text-xs leading-5 text-zinc-200 placeholder:text-zinc-600"
      />
      <div className="mt-2 flex items-center justify-between gap-3">
        <span className="text-[10px] text-zinc-600">{message.length}/4000</span>
        <button type="submit" disabled={!canSubmit} className="focus-ring inline-flex items-center gap-1.5 rounded-lg bg-violet-600 px-3 py-2 text-xs font-bold text-white transition hover:bg-violet-500 disabled:cursor-not-allowed disabled:opacity-40">
          {submitting ? <LoaderCircle size={14} className="animate-spin" /> : <Send size={14} />}
          {submitting ? "Queuing revision…" : "Request revision"}
        </button>
      </div>
      {error && <p className="mt-2 rounded-md border border-rose-500/20 bg-rose-500/10 px-2.5 py-2 text-[11px] leading-4 text-rose-300">{error}</p>}
      {voiceError && <p className="mt-2 rounded-md border border-rose-500/20 bg-rose-500/10 px-2.5 py-2 text-[11px] leading-4 text-rose-300">{voiceError}</p>}
      <p className="mt-2 text-[10px] leading-4 text-zinc-600">Record synthetic or de-identified guidance only. Audio is sent to the configured Meta Model API and is not stored by this workbench.</p>
    </form>
  );
}

const REVIEW_STAGE_LABELS: Record<NonNullable<Job["review_stage"]>, string> = {
  edc_source: "EDC source specification",
  domain_mapping: "SDTM domain mapping",
  variable_mapping: "SDTM variable and value-level mapping",
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
