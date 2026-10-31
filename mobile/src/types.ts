export type Workflow = "protocol-extraction" | "clinical-document" | "edc-design" | "sdtm" | "tlf";
export type JobStatus = "queued" | "running" | "review_required" | "succeeded" | "failed";

export interface Artifact {
  id: string;
  name: string;
  media_type: string;
  size_bytes: number;
  sha256: string;
  download_url: string;
}

export interface Job {
  id: string;
  workflow: Workflow;
  title: string;
  status: JobStatus;
  model_name: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  review_stage: string | null;
  result: Record<string, unknown> | unknown[] | null;
  warnings: string[];
  error: string | null;
  artifacts: Artifact[];
}

export interface JobList {
  items: Job[];
  total: number;
  page: number;
  page_size: number;
}

export interface AgentEvent {
  turn: number;
  type: string;
  actor?: "agent" | "user" | "system";
  name?: string | null;
  stage?: string | null;
  ok?: boolean | null;
  error?: string | null;
  summary?: string | null;
  intent?: string | null;
  input_summary?: string | null;
  output_summary?: string | null;
  input_details?: Record<string, unknown>;
  output_details?: Record<string, unknown>;
  evidence?: string[];
  duration_ms?: number | null;
  occurred_at?: string | null;
}

export interface AgentProgress {
  agent_id: string;
  workflow: string;
  status: string;
  model: string | null;
  turn: number;
  max_turns: number;
  stage: string | null;
  stage_index: number;
  stage_count: number;
  completed_stages: string[];
  total_source_chunks: number;
  read_source_chunks: number[];
  started_at?: string | null;
  updated_at?: string | null;
  events: AgentEvent[];
}

export interface Health {
  status: string;
  database: string;
  storage: string;
  meta_configured: boolean;
  meta_model: string | null;
}
