import { ChatResponse, Document, ResearchJobDetail, ResearchJobSummary, SearchResult, TokenResponse, User, Workspace } from "@/types";

export const AUTH_EXPIRED_EVENT = "auth:expired";

export const Config = {
  apiUrl: (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(
    /\/+$/,
    ""
  ),
};

export class ApiRequestError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiRequestError";
    this.status = status;
  }
}

export function getStoredToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("auth_token");
}

export function setStoredToken(token: string, email?: string): void {
  if (typeof window === "undefined") return;
  localStorage.setItem("auth_token", token);
  if (email) {
    localStorage.setItem("user_email", email);
  }
}

export function clearStoredToken(): void {
  if (typeof window === "undefined") return;
  localStorage.removeItem("auth_token");
  localStorage.removeItem("user_email");
}

export function getStoredUserEmail(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("user_email");
}

export async function apiFetch<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const token = getStoredToken();
  const headers = new Headers(options.headers);
  if (!(options.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const url = `${Config.apiUrl}${endpoint}`;
  let response: Response;
  try {
    response = await fetch(url, {
      ...options,
      headers,
    });
  } catch (err: unknown) {
    if (err instanceof ApiRequestError) {
      throw err;
    }
    throw new ApiRequestError(
      "Cannot connect to server. Please ensure the backend is running.",
      0
    );
  }

  if (response.status === 204) {
    return null as T;
  }

  if (!response.ok) {
    let errorMessage = `HTTP error ${response.status}`;
    try {
      const errorJson = await response.json();
      if (typeof errorJson.detail === "string") {
        errorMessage = errorJson.detail;
      } else if (Array.isArray(errorJson.detail)) {
        errorMessage = errorJson.detail.map((e: { msg?: string }) => e.msg || "").join(", ");
      }
    } catch {
      // Fallback to response.statusText
      errorMessage = response.statusText || errorMessage;
    }

    if (response.status === 401 && token && !endpoint.startsWith("/auth/") && typeof window !== "undefined") {
      clearStoredToken();
      window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT));
    }

    throw new ApiRequestError(errorMessage, response.status);
  }

  return response.json();
}

export const authApi = {
  register: (email: string, password: string): Promise<User> =>
    apiFetch<User>("/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),

  login: (email: string, password: string): Promise<TokenResponse> =>
    apiFetch<TokenResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
};

export const workspacesApi = {
  chat: (id: string, message: string, signal?: AbortSignal): Promise<ChatResponse> =>
    apiFetch(`/workspaces/${id}/chat`, {
      method: "POST", body: JSON.stringify({ message }), signal,
    }),
  list: (): Promise<Workspace[]> => apiFetch<Workspace[]>("/workspaces"),

  get: (id: string): Promise<Workspace> => apiFetch<Workspace>(`/workspaces/${id}`),

  create: (data: { name: string; description?: string }): Promise<Workspace> =>
    apiFetch<Workspace>("/workspaces", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  delete: (id: string): Promise<void> =>
    apiFetch<void>(`/workspaces/${id}`, {
      method: "DELETE",
    }),
};

export const documentsApi = {
  list: (workspaceId: string): Promise<Document[]> => apiFetch(`/workspaces/${workspaceId}/documents`),
  upload: (workspaceId: string, file: File, chunkSize: number): Promise<Document> => {
    const body = new FormData();
    body.append("file", file);
    body.append("chunk_size", String(chunkSize));
    body.append("chunk_overlap", "64");
    return apiFetch(`/workspaces/${workspaceId}/documents`, { method: "POST", body });
  },
  delete: (workspaceId: string, documentId: string): Promise<void> =>
    apiFetch(`/workspaces/${workspaceId}/documents/${documentId}`, { method: "DELETE" }),
  search: (workspaceId: string, query: string, topK: number, method: "vector" | "bm25" | "hybrid" | "hybrid_reranked" = "vector"): Promise<SearchResult[]> =>
    apiFetch(`/workspaces/${workspaceId}/search`, {
      method: "POST", body: JSON.stringify({ query, top_k: topK, method }),
    }),
};

export const researchApi = {
  list: (workspaceId: string, signal?: AbortSignal): Promise<ResearchJobSummary[]> =>
    apiFetch(`/workspaces/${workspaceId}/research-jobs`, { signal }),
  get: (workspaceId: string, jobId: string, signal?: AbortSignal): Promise<ResearchJobDetail> =>
    apiFetch(`/workspaces/${workspaceId}/research-jobs/${jobId}`, { signal }),
  create: (workspaceId: string, query: string): Promise<ResearchJobDetail> =>
    apiFetch(`/workspaces/${workspaceId}/research-jobs`, {
      method: "POST", body: JSON.stringify({ query }),
    }),
};
