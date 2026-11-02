import type { AgentProgress, CDISCDataset, ExecutionAttempt, Health, Job, JobList, ReviewScope, ReviewScopeProposal, UseCaseContract, ValidationFinding, ValidationRecord, Workflow } from "./types";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, { ...init, cache: "no-store" });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      message = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch { /* keep the HTTP fallback */ }
    throw new Error(message);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

async function requestText(path: string): Promise<string> {
  const response = await fetch(`${API_URL}${path}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`Unable to load artifact (${response.status}).`);
  return response.text();
}

export const api = {
  health: () => request<Health>("/api/v1/health"),
  useCases: () => request<UseCaseContract[]>("/api/v1/use-cases"),
  useCase: (id: Workflow) => request<UseCaseContract>(`/api/v1/use-cases/${id}`),
  jobs: (workflow?: Workflow, page = 1, pageSize = 20) => {
    const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
    if (workflow) params.set("workflow", workflow);
    return request<JobList>(`/api/v1/jobs?${params.toString()}`);
  },
  job: (id: string) => request<Job>(`/api/v1/jobs/${id}`),
  agentProgress: (id: string) => request<AgentProgress>(`/api/v1/jobs/${id}/agent`),
  sdtmDataset: (domain: string, version: string, standard: "sdtm" | "sdtmig" = "sdtmig") =>
    request<CDISCDataset>(`/api/v1/standards/sdtm/datasets/${encodeURIComponent(domain)}?version=${encodeURIComponent(version)}&standard=${standard}`),
  createJob: (workflow: Workflow, options: Record<string, unknown>, files: File[], sdtm?: { rawFiles?: File[]; crfFile?: File | null; validationReport?: File | null }) => {
    const data = new FormData();
    data.set("options", JSON.stringify(options));
    files.forEach((file) => data.append("files", file));
    sdtm?.rawFiles?.forEach((file) => data.append("raw_files", file));
    if (sdtm?.crfFile) data.set("crf_file", sdtm.crfFile);
    if (sdtm?.validationReport) data.set("validation_report", sdtm.validationReport);
    return request<Job>(`/api/v1/jobs/${workflow}`, { method: "POST", body: data });
  },
  retryJob: (id: string) => request<Job>(`/api/v1/jobs/${id}/retry`, { method: "POST" }),
  submitReviewFeedback: (id: string, update: { message: string; scope: ReviewScope; baseline_revision: string; current_result: Record<string, unknown> }) =>
    request<Job>(`/api/v1/jobs/${id}/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(update),
    }),
  proposeReviewScope: (id: string, message: string, currentResult: Record<string, unknown>) =>
    request<ReviewScopeProposal>(`/api/v1/jobs/${id}/feedback/scope`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, current_result: currentResult }),
    }),
  decideReviewPatch: (id: string, transactionId: string, approved: boolean, expectedRevision: string, currentResult: Record<string, unknown>, reviewer = "Workbench reviewer") =>
    request<Job>(`/api/v1/jobs/${id}/feedback/${transactionId}/decision`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approved, expected_revision: expectedRevision, current_result: currentResult, reviewer }),
    }),
  transcribeReviewAudio: (id: string, audio: Blob) => {
    const data = new FormData();
    data.set("audio", audio, "guidance.wav");
    return request<{ transcript: string; model: string; duration_ms: number | null; session_id: string | null }>(
      `/api/v1/jobs/${id}/transcription`,
      { method: "POST", body: data },
    );
  },
  approveEdcSource: (id: string, sourceSpec: Record<string, unknown>) =>
    request<Job>(`/api/v1/jobs/${id}/edc-source-spec`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source_spec: sourceSpec }),
    }),
  approveSdtmDomainMapping: (id: string, domainMapping: Record<string, unknown>) =>
    request<Job>(`/api/v1/jobs/${id}/sdtm-domain-mapping`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ domain_mapping: domainMapping }),
    }),
  reopenSdtmDomainMapping: (id: string) =>
    request<Job>(`/api/v1/jobs/${id}/sdtm-domain-mapping/reopen`, { method: "POST" }),
  approveSdtmVariableMapping: (id: string, variableMapping: Record<string, unknown>) =>
    request<Job>(`/api/v1/jobs/${id}/sdtm-variable-mapping`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ variable_mapping: variableMapping }),
    }),
  rerunSdtmDomain: (
    id: string,
    stage: "domain_mapping" | "variable_mapping" | "rule_augmentation",
    domain?: string,
    options?: { guidance?: string; executionAttemptId?: string; scope?: ReviewScope },
  ) =>
    request<Job>(`/api/v1/jobs/${id}/sdtm-domain-reruns`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        stage,
        ...(domain ? { domain } : {}),
        ...(options?.guidance ? { guidance: options.guidance } : {}),
        ...(options?.executionAttemptId ? { execution_attempt_id: options.executionAttemptId } : {}),
        ...(options?.scope ? { scope: options.scope } : {}),
      }),
    }),
  approveTlfInventory: (id: string, inventoryPlan: Record<string, unknown>) =>
    request<Job>(`/api/v1/jobs/${id}/tlf-inventory`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ inventory_plan: inventoryPlan }),
    }),
  approveTlfShell: (id: string, shellPlan: Record<string, unknown>) =>
    request<Job>(`/api/v1/jobs/${id}/tlf-shell`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ shell_plan: shellPlan }),
    }),
  approveTlfProgramming: (id: string, programmingPlan: Record<string, unknown>) =>
    request<Job>(`/api/v1/jobs/${id}/tlf-programming`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ programming_plan: programmingPlan }),
    }),
  updateJobResult: (id: string, result: Record<string, unknown>) =>
    request<Job>(`/api/v1/jobs/${id}/result`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ result }),
    }),
  sdtmExecutions: (id: string) => request<{ items: ExecutionAttempt[] }>(`/api/v1/jobs/${id}/sdtm-executions`),
  updateSdtmProgram: (id: string, domain: string, language: "r" | "sas", code: string, expectedSha256: string, reviewer = "Workbench reviewer") =>
    request<Job>(`/api/v1/jobs/${id}/sdtm-programs/${encodeURIComponent(domain)}/${language}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code, expected_sha256: expectedSha256, reviewer }),
    }),
  executeSdtm: (id: string, rawFiles: File[] = []) => {
    const data = new FormData();
    rawFiles.forEach((file) => data.append("raw_files", file));
    return request<ExecutionAttempt>(`/api/v1/jobs/${id}/sdtm-executions`, { method: "POST", body: data });
  },
  reviewSdtmRepair: (id: string, attemptId: string, proposalId: string, approved: boolean, reviewer = "Workbench reviewer") =>
    request<ExecutionAttempt>(`/api/v1/jobs/${id}/sdtm-executions/${attemptId}/repair`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ proposal_id: proposalId, approved, reviewer }),
    }),
  validations: (id: string) => request<ValidationRecord[]>(`/api/v1/jobs/${id}/validations`),
  importValidation: (id: string, report?: File | null) => {
    const data = new FormData();
    if (report) data.set("report", report);
    return request<ValidationRecord>(`/api/v1/jobs/${id}/validations/import`, { method: "POST", body: data });
  },
  runValidation: (id: string, provider: "internal" | "pinnacle21-cli") => request<ValidationRecord>(`/api/v1/jobs/${id}/validations/run`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ provider }) }),
  updateValidationFinding: (id: string, findingId: string, update: Record<string, unknown>) => request<ValidationFinding>(`/api/v1/jobs/${id}/validation-findings/${findingId}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(update) }),
  updateCsdrg: (id: string, document: Record<string, unknown>) => request<Record<string, unknown>>(`/api/v1/jobs/${id}/csdrg`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(document) }),
  reviseCsdrgWithAgent: (id: string, guidance: string, scope?: ReviewScope) => request<Record<string, unknown>>(`/api/v1/jobs/${id}/csdrg/agent-revision`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ guidance, ...(scope ? { scope } : {}) }) }),
  deleteJob: (id: string) => request<void>(`/api/v1/jobs/${id}`, { method: "DELETE" }),
  artifactUrl: (path: string) => `${API_URL}${path}`,
  artifactPreviewUrl: (path: string) => `${API_URL}${path}?inline=true`,
  artifactPageUrl: (path: string, page: number) => `${API_URL}${path}/pages/${page}.png`,
  artifactText: (path: string) => requestText(`${path}?inline=true`),
  bundleUrl: (id: string) => `${API_URL}/api/v1/jobs/${id}/bundle`,
};
