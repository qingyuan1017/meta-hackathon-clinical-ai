"use client";

import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

interface ReviewDraftContextValue {
  currentResult: Record<string, unknown> | null;
  setCurrentResult: (value: Record<string, unknown> | null) => void;
}

const ReviewDraftContext = createContext<ReviewDraftContextValue | null>(null);

export function ReviewDraftProvider({ jobId, children }: { jobId: string | null; children: ReactNode }) {
  const [currentResult, setCurrentResult] = useState<Record<string, unknown> | null>(null);
  useEffect(() => setCurrentResult(null), [jobId]);
  const value = useMemo(() => ({ currentResult, setCurrentResult }), [currentResult]);
  return <ReviewDraftContext.Provider value={value}>{children}</ReviewDraftContext.Provider>;
}

export function useReviewDraft() {
  const value = useContext(ReviewDraftContext);
  if (!value) throw new Error("useReviewDraft must be used inside ReviewDraftProvider");
  return value;
}
