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
  sdtm_workbench?: SDTMWorkbenchState | null;
}

export interface JobList { items: Job[]; total: number; page: number; page_size: number; }

export type Health = components["schemas"]["HealthRead"];
export type UseCaseContract = components["schemas"]["UseCaseRead"];
export type AgentProgress = components["schemas"]["AgentProgressRead"];
export type CDISCDataset = components["schemas"]["CDISCDatasetRead"];

export interface SDTMWorkbenchState {
  lifecycle: { program_generation: string; execution: string; validation: string; submission_readiness: string };
  inputs: { raw_datasets: Array<{ logical_name: string; format: string; row_count: number | null; columns: Array<{ name: string; data_type: string }>; sha256: string }>; blank_crf: string | null; validation_report: string | null };
  limitations: string[];
}

export interface ExecutionAttempt {
  attempt_id: string; parent_attempt_id: string | null; status: string; created_at: string; completed_at: string | null;
  program_hash: string; runtime: Record<string, string>; exit_code: number | null; stdout: string; stderr: string;
  outputs: Array<{ name: string; sha256: string; size_bytes: number; row_count: number | null; columns: string[] }>;
  checks: Array<{ check_id: string; status: string; message: string; domain: string | null }>;
  failure_classification: string | null;
}
