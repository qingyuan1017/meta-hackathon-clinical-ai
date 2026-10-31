import type { JobStatus, Workflow } from "./types";

export const workflowLabels: Record<Workflow, string> = {
  "protocol-extraction": "Protocol extraction",
  "clinical-document": "Document generation",
  "edc-design": "EDC design",
  sdtm: "SDTM artifacts",
  tlf: "TLF artifacts",
};

export const workflowIcons: Record<Workflow, "code-braces" | "file-document-outline" | "view-dashboard-outline" | "database-outline" | "table-large"> = {
  "protocol-extraction": "code-braces",
  "clinical-document": "file-document-outline",
  "edc-design": "view-dashboard-outline",
  sdtm: "database-outline",
  tlf: "table-large",
};

export function humanize(value: string) {
  return value.replaceAll("_", " ").replaceAll("-", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function relativeTime(value: string) {
  const delta = Date.now() - new Date(value).getTime();
  if (!Number.isFinite(delta)) return "";
  if (delta < 60_000) return "now";
  if (delta < 3_600_000) return `${Math.floor(delta / 60_000)}m`;
  if (delta < 86_400_000) return `${Math.floor(delta / 3_600_000)}h`;
  return `${Math.floor(delta / 86_400_000)}d`;
}

export function formatDate(value: string) {
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

export function renderValue(value: unknown): string {
  if (Array.isArray(value)) return value.map(renderValue).join(" · ") || "None";
  if (value && typeof value === "object") return Object.entries(value as Record<string, unknown>).map(([key, item]) => `${humanize(key)}: ${renderValue(item)}`).join(" · ");
  if (value === null || value === undefined || value === "") return "None";
  return String(value);
}

export function isActive(status: JobStatus) {
  return status === "queued" || status === "running";
}

export interface RevisionDecision {
  unresolved: string[];
  assumptions: string[];
}

export interface FeedbackDecisionEntry {
  eventIndex: number;
  feedback: string;
  decisions: string[];
}

export function getRevisionDecision(result: unknown, warnings: string[] = []): RevisionDecision {
  const unresolved: string[] = [];
  const assumptions: string[] = [];
  collectDecisionItems(result, unresolved, assumptions);
  if (!unresolved.length) unresolved.push(...warnings.filter((warning) => warning && !warning.startsWith("DRAFT — HACKATHON DEMONSTRATION ONLY")));
  return { unresolved: Array.from(new Set(unresolved)), assumptions: Array.from(new Set(assumptions)) };
}

export function getFeedbackDecisionSequence(result: unknown, warnings: string[] = [], events: Array<{ actor?: string; type: string; summary?: string | null }> = []) {
  const decision = getRevisionDecision(result, warnings);
  const unmatched = [...decision.unresolved];
  const entries: FeedbackDecisionEntry[] = [];
  events.forEach((event, eventIndex) => {
    if (event.actor !== "user" && event.type !== "user_feedback") return;
    const feedback = event.summary?.trim();
    if (!feedback) return;
    const normalizedFeedback = normalize(feedback);
    const decisions = unmatched.filter((item) => decisionMatchesFeedback(item, normalizedFeedback));
    decisions.forEach((item) => unmatched.splice(unmatched.indexOf(item), 1));
    entries.push({ eventIndex, feedback, decisions });
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
    if (key === "unresolved_items" || key === "unresolved_mappings") unresolved.push(...stringItems(item));
    else if (key === "assumptions") assumptions.push(...stringItems(item));
    else collectDecisionItems(item, unresolved, assumptions);
  });
}

function stringItems(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string").map((item) => item.trim()).filter(Boolean)
    : [];
}

function decisionMatchesFeedback(decision: string, normalizedFeedback: string): boolean {
  const normalizedDecision = normalize(decision);
  if (normalizedDecision.includes(normalizedFeedback)) return true;
  return Array.from(decision.matchAll(/[\"'“”‘’]([^\"'“”‘’]+)[\"'“”‘’]/g), (match) => normalize(match[1] ?? ""))
    .some((phrase) => phrase === normalizedFeedback || normalizedFeedback.includes(phrase) || phrase.includes(normalizedFeedback));
}

function normalize(value: string): string {
  return value.toLocaleLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
}
