"use client";

import { createContext, useContext, useMemo, useState, type ReactNode } from "react";

export interface SDTMRevisionContext {
  surface: "domain_mapping" | "variable_mapping" | "rule_augmentation" | "execution" | "acrf" | "define_xml" | "csdrg";
  label: string;
  domain?: string;
  variable?: string;
  executionAttemptId?: string;
}

interface ReviewDraftContextValue {
  currentResult: Record<string, unknown> | null;
  setCurrentResult: (value: Record<string, unknown> | null) => void;
  sdtmRevisionContext: SDTMRevisionContext | null;
  setSdtmRevisionContext: (value: SDTMRevisionContext | null) => void;
  csdrgAgentDraft: Record<string, unknown> | null;
  setCsdrgAgentDraft: (value: Record<string, unknown> | null) => void;
}

const ReviewDraftContext = createContext<ReviewDraftContextValue | null>(null);

export function ReviewDraftProvider({ jobId, children }: { jobId: string | null; children: ReactNode }) {
  return <ReviewDraftStateProvider key={jobId ?? "no-job"}>{children}</ReviewDraftStateProvider>;
}

function ReviewDraftStateProvider({ children }: { children: ReactNode }) {
  const [currentResult, setCurrentResult] = useState<Record<string, unknown> | null>(null);
  const [sdtmRevisionContext, setSdtmRevisionContext] = useState<SDTMRevisionContext | null>(null);
  const [csdrgAgentDraft, setCsdrgAgentDraft] = useState<Record<string, unknown> | null>(null);
  const value = useMemo(() => ({
    currentResult,
    setCurrentResult,
    sdtmRevisionContext,
    setSdtmRevisionContext,
    csdrgAgentDraft,
    setCsdrgAgentDraft,
  }), [currentResult, sdtmRevisionContext, csdrgAgentDraft]);
  return <ReviewDraftContext.Provider value={value}>{children}</ReviewDraftContext.Provider>;
}

export function useReviewDraft() {
  const value = useContext(ReviewDraftContext);
  if (!value) throw new Error("useReviewDraft must be used inside ReviewDraftProvider");
  return value;
}

export function useOptionalReviewDraft() {
  return useContext(ReviewDraftContext);
}
