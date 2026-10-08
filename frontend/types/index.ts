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
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export interface ApiError {
  detail: string;
}
