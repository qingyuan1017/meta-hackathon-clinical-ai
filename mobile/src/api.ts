import type { AgentProgress, Health, Job, JobList } from "./types";

async function request<T>(baseUrl: string, path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15_000);
  try {
    const response = await fetch(`${baseUrl}${path}`, { ...init, signal: controller.signal });
    if (!response.ok) {
      let message = `Request failed (${response.status})`;
      try {
        const body = await response.json() as { detail?: unknown };
        if (typeof body.detail === "string") message = body.detail;
      } catch { /* use status fallback */ }
      throw new Error(message);
    }
    return await response.json() as T;
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") throw new Error("The backend did not respond in time.");
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

export const mobileApi = {
  health: (baseUrl: string) => request<Health>(baseUrl, "/api/v1/health"),
  jobs: (baseUrl: string) => request<JobList>(baseUrl, "/api/v1/jobs?page=1&page_size=50"),
  job: (baseUrl: string, id: string) => request<Job>(baseUrl, `/api/v1/jobs/${id}`),
  progress: (baseUrl: string, id: string) => request<AgentProgress>(baseUrl, `/api/v1/jobs/${id}/agent`),
  sendFeedback: (baseUrl: string, id: string, message: string) => request<Job>(baseUrl, `/api/v1/jobs/${id}/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  }),
  retry: (baseUrl: string, id: string) => request<Job>(baseUrl, `/api/v1/jobs/${id}/retry`, { method: "POST" }),
  artifactUrl: (baseUrl: string, path: string) => `${baseUrl}${path}`,
};
