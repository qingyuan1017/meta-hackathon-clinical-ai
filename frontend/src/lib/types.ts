import type { components } from "./openapi";

export type Workflow = "protocol-extraction" | "clinical-document" | "edc-design" | "sdtm" | "tlf";
export type JobStatus = "queued" | "running" | "review_required" | "succeeded" | "failed";
export type ReviewStage = "edc_source" | "domain_mapping" | "variable_mapping" | "tlf_inventory" | "tlf_shell" | "tlf_programming";

export type Artifact = components["schemas"]["ArtifactRead"];

export interface Job extends Omit<components["schemas"]["JobRead"], "workflow" | "status" | "result" | "error" | "warnings" | "artifacts" | "review_stage"> {
  workflow: Workflow;
  status: JobStatus;
  result: Record<string, unknown> | unknown[] | null;
  error: string | null;
  warnings: string[];
  artifacts: Artifact[];
  review_stage: ReviewStage | null;
}

export interface JobList { items: Job[]; total: number; page: number; page_size: number; }

export type Health = components["schemas"]["HealthRead"];
export type UseCaseContract = components["schemas"]["UseCaseRead"];
export type AgentProgress = components["schemas"]["AgentProgressRead"];
export type CDISCDataset = components["schemas"]["CDISCDatasetRead"];
