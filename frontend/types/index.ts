export interface User {
  id: string;
  email: string;
  created_at: string;
}

export interface Workspace {
  id: string;
  name: string;
  description: string | null;
  user_id: string;
  created_at: string;
}

export interface Document {
  id: string;
  workspace_id: string;
  filename: string;
  status: string;
  error: string | null;
  chunk_count: number;
  created_at: string;
  updated_at: string;
  attempt_count: number;
  max_attempts: number;
  next_retry_at: string | null;
}

export interface SearchResult {
  chunk_id: string;
  document_id: string;
  filename: string;
  content: string;
  page: number;
  chunk_index: number;
  similarity: number | null;
  bm25_score?: number | null;
  rerank_score?: number | null;
  rerank_status?: "applied" | "fallback" | null;
  fusion_score?: number | null;
  vector_rank?: number | null;
  bm25_rank?: number | null;
  retrieval_method?: "vector" | "bm25" | "hybrid" | "hybrid_reranked";
  metadata: Record<string, unknown>;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export interface ApiError {
  detail: string;
}

export interface ChatSource {
  id: number;
  document: string;
  document_id: string;
  page: number;
  chunk_id: string;
  quote: string;
}

export interface ChatResponse {
  answer: string;
  sources: ChatSource[];
  retrieved_chunks: SearchResult[];
  status: "answered" | "insufficient_evidence";
}

export type ResearchStage = "PLANNING" | "RETRIEVING" | "SYNTHESIZING" | "VERIFYING" | "COMPLETED";
export type ResearchStatus = "queued" | "running" | "retrying" | "completed" | "failed";

export interface ResearchJobSummary {
  id: string;
  workspace_id: string;
  query: string;
  status: ResearchStatus;
  current_stage: ResearchStage;
  retrieval_method: string;
  error: string | null;
  attempt_count: number;
  max_attempts: number;
  next_retry_at: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface ResearchEvidence {
  source_id: number;
  chunk_id: string;
  document_id: string;
  filename: string;
  page: number;
  content: string;
  question_indices: number[];
}

export interface ResearchReport {
  sections: { question: string; claims: { text: string; citation_ids: number[] }[] }[];
  sources: ChatSource[];
  gaps: string[];
}

export interface ResearchJobDetail extends ResearchJobSummary {
  plan: { questions: string[] } | null;
  evidence: ResearchEvidence[] | null;
  result: ResearchReport | null;
}
