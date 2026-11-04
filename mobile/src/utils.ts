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
