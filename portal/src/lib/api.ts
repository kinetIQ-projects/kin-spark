import { supabase } from "./supabase";

const API_BASE = import.meta.env.VITE_API_BASE || "/spark/admin";

/**
 * Authenticated fetch wrapper for admin API calls.
 *
 * - Attaches Bearer token from Supabase session
 * - On 401: attempts token refresh, retries once
 * - On refresh failure: clears session, redirects to /login
 */
export async function apiFetch<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const {
    data: { session },
  } = await supabase.auth.getSession();

  if (!session) {
    window.location.href = "/login";
    throw new Error("No session");
  }

  const url = `${API_BASE}${path}`;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Authorization: `Bearer ${session.access_token}`,
    ...(options.headers as Record<string, string>),
  };

  let response = await fetch(url, { ...options, headers });

  // 401 → refresh token and retry once
  if (response.status === 401) {
    const { data: refreshData, error } =
      await supabase.auth.refreshSession();

    if (error || !refreshData.session) {
      await supabase.auth.signOut();
      window.location.href = "/login";
      throw new Error("Session expired");
    }

    headers.Authorization = `Bearer ${refreshData.session.access_token}`;
    response = await fetch(url, { ...options, headers });
  }

  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new ApiError(
      response.status,
      (body as { detail?: string }).detail || response.statusText
    );
  }

  // Handle empty responses (204)
  if (response.status === 204) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}

/**
 * Fetch that returns a Blob (for CSV export).
 */
export async function apiFetchBlob(path: string): Promise<Blob> {
  const {
    data: { session },
  } = await supabase.auth.getSession();

  if (!session) {
    window.location.href = "/login";
    throw new Error("No session");
  }

  const url = `${API_BASE}${path}`;
  const response = await fetch(url, {
    headers: {
      Authorization: `Bearer ${session.access_token}`,
    },
  });

  if (!response.ok) {
    throw new ApiError(response.status, response.statusText);
  }

  return response.blob();
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string
  ) {
    super(message);
    this.name = "ApiError";
  }
}
