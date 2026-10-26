export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem("recircle_token");
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((init?.headers as Record<string, string>) ?? {}),
  };
  const token = getToken();
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  const response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers });
  if (!response.ok) {
    if (response.status === 401) {
      window.localStorage.removeItem("recircle_token");
      window.localStorage.removeItem("recircle_user");
    }
    let detail = `Request failed: ${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (typeof body?.detail === "string") {
        detail = body.detail;
      } else if (Array.isArray(body?.detail)) {
        detail = body.detail
          .map((item: { loc?: (string | number)[]; msg?: string }) =>
            `${item.loc?.slice(1).join(".") ?? "field"}: ${item.msg ?? "invalid"}`,
          )
          .join("; ");
      }
    } catch {
      // keep default detail
    }
    throw new ApiError(response.status, detail);
  }
  return response.json() as Promise<T>;
}
