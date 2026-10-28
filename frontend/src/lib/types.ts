import type { components } from "./openapi";

export type Workflow = "protocol-extraction" | "clinical-document" | "edc-design" | "sdtm" | "tlf";
export type JobStatus = "queued" | "running" | "succeeded" | "failed";

export type Artifact = components["schemas"]["ArtifactRead"];

export interface Job extends Omit<components["schemas"]["JobRead"], "workflow" | "status" | "result" | "error" | "warnings" | "artifacts"> {
  workflow: Workflow;
  status: JobStatus;
  result: Record<string, unknown> | unknown[] | null;
  error: string | null;
  warnings: string[];
  artifacts: Artifact[];
}

export interface JobList { items: Job[]; total: number; page: number; page_size: number; }

export type Health = components["schemas"]["HealthRead"];
export type UseCaseContract = components["schemas"]["UseCaseRead"];
export type AgentProgress = components["schemas"]["AgentProgressRead"];
export type CDISCDataset = components["schemas"]["CDISCDatasetRead"];
