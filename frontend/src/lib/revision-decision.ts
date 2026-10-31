export interface RevisionDecision {
  unresolved: string[];
  assumptions: string[];
}

export interface RevisionFeedbackEvent {
  actor?: string | null;
  type: string;
  summary?: string | null;
}

export interface FeedbackDecisionEntry {
  eventIndex: number;
  feedback: string;
  decisions: string[];
}

export interface FeedbackDecisionSequence {
  entries: FeedbackDecisionEntry[];
  unmatched: string[];
  assumptions: string[];
}

const UNRESOLVED_KEYS = new Set(["unresolved_items", "unresolved_mappings"]);
const DISCLAIMER_PREFIX = "DRAFT — HACKATHON DEMONSTRATION ONLY";

export function getRevisionDecision(result: unknown, warnings: string[] = []): RevisionDecision {
  const unresolved: string[] = [];
  const assumptions: string[] = [];
  collectDecisionItems(result, unresolved, assumptions);

  if (!unresolved.length) {
    unresolved.push(...warnings.filter((warning) => warning && !warning.startsWith(DISCLAIMER_PREFIX)));
  }

  return {
    unresolved: unique(unresolved),
    assumptions: unique(assumptions),
  };
}

export function getFeedbackDecisionSequence(
  result: unknown,
  warnings: string[] = [],
  events: RevisionFeedbackEvent[] = [],
): FeedbackDecisionSequence {
  const decision = getRevisionDecision(result, warnings);
  const unmatched = [...decision.unresolved];
  const entries = events.flatMap((event, eventIndex) => {
    if (event.actor !== "user" && event.type !== "user_feedback") return [];
    const feedback = event.summary?.trim();
    if (!feedback) return [];
    const normalizedFeedback = normalize(feedback);
    const decisions = unmatched.filter((item) => decisionMatchesFeedback(item, normalizedFeedback));
    decisions.forEach((item) => unmatched.splice(unmatched.indexOf(item), 1));
    return [{ eventIndex, feedback, decisions }];
  });
  return { entries, unmatched, assumptions: decision.assumptions };
}

function collectDecisionItems(value: unknown, unresolved: string[], assumptions: string[]): void {
  if (!value || typeof value !== "object") return;
  if (Array.isArray(value)) {
    value.forEach((item) => collectDecisionItems(item, unresolved, assumptions));
    return;
  }

  Object.entries(value as Record<string, unknown>).forEach(([key, item]) => {
    if (UNRESOLVED_KEYS.has(key)) {
      unresolved.push(...stringItems(item));
      return;
    }
    if (key === "assumptions") {
      assumptions.push(...stringItems(item));
      return;
    }
    collectDecisionItems(item, unresolved, assumptions);
  });
}

function stringItems(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string").map((item) => item.trim()).filter(Boolean)
    : [];
}

function unique(items: string[]): string[] {
  return Array.from(new Set(items));
}

function decisionMatchesFeedback(decision: string, normalizedFeedback: string): boolean {
  const normalizedDecision = normalize(decision);
  if (normalizedDecision.includes(normalizedFeedback)) return true;
  return quotedPhrases(decision).some((phrase) => {
    const normalizedPhrase = normalize(phrase);
    return normalizedPhrase === normalizedFeedback
      || normalizedFeedback.includes(normalizedPhrase)
      || normalizedPhrase.includes(normalizedFeedback);
  });
}

function quotedPhrases(value: string): string[] {
  return Array.from(value.matchAll(/[\"'“”‘’]([^\"'“”‘’]+)[\"'“”‘’]/g), (match) => match[1]);
}

function normalize(value: string): string {
  return value.toLocaleLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
}
