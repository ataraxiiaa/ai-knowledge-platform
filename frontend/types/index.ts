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
}

export interface SearchResult {
  chunk_id: string;
  document_id: string;
  filename: string;
  content: string;
  page: number;
  chunk_index: number;
  similarity: number;
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
