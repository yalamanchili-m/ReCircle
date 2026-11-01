"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { getStoredUser, getToken } from "./auth";
import type { UserSummary } from "./types";

/**
 * Client-side route guard (defense in depth — the backend remains the
 * authority). Redirects unauthenticated visitors to /login and visitors
 * without an allowed role to /dashboard. Returns `ready` so pages can
 * avoid fetching until the session check has completed.
 */
export function useRequireAuth(allowedRoles?: string[]) {
  const router = useRouter();
  const [ready, setReady] = useState(false);
  const [user, setUser] = useState<UserSummary | null>(null);

  useEffect(() => {
    const token = getToken();
    const stored = getStoredUser();
    if (!token || !stored) {
      router.replace("/login");
      return;
    }
    if (allowedRoles && !allowedRoles.includes(stored.role)) {
      router.replace("/dashboard");
      return;
    }
    setUser(stored);
    setReady(true);
  }, [router, allowedRoles]);

  return { ready, user };
}
