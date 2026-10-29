import type { AgentProgress, CDISCDataset, Health, Job, JobList, UseCaseContract, Workflow } from "./types";

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
  jobs: (workflow?: Workflow) => request<JobList>(`/api/v1/jobs${workflow ? `?workflow=${workflow}` : ""}`),
  job: (id: string) => request<Job>(`/api/v1/jobs/${id}`),
  agentProgress: (id: string) => request<AgentProgress>(`/api/v1/jobs/${id}/agent`),
  sdtmDataset: (domain: string, version: string, standard: "sdtm" | "sdtmig" = "sdtmig") =>
    request<CDISCDataset>(`/api/v1/standards/sdtm/datasets/${encodeURIComponent(domain)}?version=${encodeURIComponent(version)}&standard=${standard}`),
  createJob: (workflow: Workflow, options: Record<string, unknown>, files: File[]) => {
    const data = new FormData();
    data.set("options", JSON.stringify(options));
    files.forEach((file) => data.append("files", file));
    return request<Job>(`/api/v1/jobs/${workflow}`, { method: "POST", body: data });
  },
  retryJob: (id: string) => request<Job>(`/api/v1/jobs/${id}/retry`, { method: "POST" }),
  approveEdcSource: (id: string, sourceSpec: Record<string, unknown>) =>
    request<Job>(`/api/v1/jobs/${id}/edc-source-spec`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source_spec: sourceSpec }),
    }),
  updateJobResult: (id: string, result: Record<string, unknown>) =>
    request<Job>(`/api/v1/jobs/${id}/result`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ result }),
    }),
  deleteJob: (id: string) => request<void>(`/api/v1/jobs/${id}`, { method: "DELETE" }),
  artifactUrl: (path: string) => `${API_URL}${path}`,
  artifactPreviewUrl: (path: string) => `${API_URL}${path}?inline=true`,
  artifactText: (path: string) => requestText(`${path}?inline=true`),
  bundleUrl: (id: string) => `${API_URL}/api/v1/jobs/${id}/bundle`,
};
