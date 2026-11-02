import type { components } from "./openapi";

export type Workflow = "protocol-extraction" | "clinical-document" | "edc-design" | "sdtm" | "tlf";
export type JobStatus = "queued" | "running" | "review_required" | "succeeded" | "failed";
export type ReviewStage = "edc_source" | "domain_mapping" | "domain_mapping_completed" | "variable_mapping" | "variable_mapping_domain" | "rule_augmentation_domain" | "tlf_inventory" | "tlf_shell" | "tlf_programming";

export type Artifact = components["schemas"]["ArtifactRead"];

export interface Job extends Omit<components["schemas"]["JobRead"], "workflow" | "status" | "result" | "error" | "warnings" | "artifacts" | "review_stage" | "sdtm_workbench"> {
  workflow: Workflow;
  status: JobStatus;
  result: Record<string, unknown> | unknown[] | null;
  error: string | null;
  warnings: string[];
  artifacts: Artifact[];
  review_stage: ReviewStage | null;
  sdtm_workbench?: SDTMWorkbenchState | null;
  result_revision: string | null;
  review_patch: ReviewPatch | null;
}

export interface ReviewVariableScope { domain: string; variable: string; fields: string[]; }
export interface ReviewScope { paths: string[]; source_datasets: string[]; target_domains: string[]; variables: ReviewVariableScope[]; }
export interface ReviewPatchOperation { path: string; before: unknown; after: unknown; }
export interface ReviewPatch {
  transaction_id: string; status: "generating" | "proposed" | "approved" | "rejected" | "conflict";
  stage: string; message: string; scope: ReviewScope; baseline_revision: string; proposed_revision: string | null;
  operations: ReviewPatchOperation[]; conflicts: string[]; submitted_at: string; decided_at: string | null; reviewer: string | null;
}
export interface ReviewScopeProposal { stage: string; scope: ReviewScope; matched_terms: string[]; requires_confirmation: boolean; explanation: string; }

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
  repair_proposal: { proposal_id: string; status: string; rationale: string; diff: string; change: { domain: string; target_variable: string; source_dataset: string; from_source_variable: string; to_source_variable: string }; reviewer: string | null; decided_at: string | null } | null;
}

export interface ValidationFinding {
  finding_id: string; provider: string; provider_version: string; rule_id: string; severity: string; dataset: string | null; variable: string | null; message: string;
  finding_status: "open" | "accepted" | "corrected" | "not_applicable" | "explained"; disposition: string | null; explanation: string | null; reviewer: string | null; approved_at: string | null;
}

export interface ValidationRecord {
  validation_id: string; provider: string; provider_version: string; status: string; created_at: string; message: string | null; findings: ValidationFinding[];
  diagnostics: { rows_read: number; findings_imported: number; unknown_columns: string[]; warnings: string[] } | null;
}
