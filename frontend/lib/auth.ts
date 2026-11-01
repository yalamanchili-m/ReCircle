import { apiFetch, ApiError } from "./api";
import type { LoginResponse, UserSummary } from "./types";

const TOKEN_KEY = "recircle_token";
const USER_KEY = "recircle_user";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function getStoredUser(): UserSummary | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as UserSummary;
  } catch {
    return null;
  }
}

export function storeSession(token: string, user: UserSummary): void {
  window.localStorage.setItem(TOKEN_KEY, token);
  window.localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearSession(): void {
  window.localStorage.removeItem(TOKEN_KEY);
  window.localStorage.removeItem(USER_KEY);
}

export async function login(email: string, password: string): Promise<UserSummary> {
  const response = await apiFetch<LoginResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  storeSession(response.access_token, response.user);
  return response.user;
}

export { ApiError };
