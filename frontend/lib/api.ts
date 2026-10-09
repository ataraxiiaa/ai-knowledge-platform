import { TokenResponse, User, Workspace } from "@/types";

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
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
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

    if (response.status === 401 && typeof window !== "undefined") {
      clearStoredToken();
      if (!window.location.pathname.startsWith("/login")) {
        window.location.href = "/login";
      }
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
