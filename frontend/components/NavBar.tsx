"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { clearSession, getStoredUser } from "@/lib/auth";
import type { UserSummary } from "@/lib/types";

export default function NavBar() {
  const router = useRouter();
  const [user, setUser] = useState<UserSummary | null>(null);

  useEffect(() => {
    setUser(getStoredUser());
  }, []);

  function handleLogout() {
    clearSession();
    setUser(null);
    router.push("/login");
  }

  const links = user
    ? user.role === "generator"
      ? [
          { href: "/dashboard", label: "Dashboard" },
          { href: "/inventory", label: "Inventory" },
          { href: "/marketplace", label: "Marketplace" },
          { href: "/pathways", label: "Pathways" },
          { href: "/analytics", label: "Analytics" },
          { href: "/esg", label: "ESG" },
        ]
      : [
          { href: "/dashboard", label: "Dashboard" },
          { href: "/inventory", label: "Inventory" },
          { href: "/marketplace", label: "Marketplace" },
          { href: "/requirements", label: "Requirements" },
          { href: "/matches", label: "Matches" },
          { href: "/pathways", label: "Pathways" },
          { href: "/analytics", label: "Analytics" },
          { href: "/symbiosis", label: "Symbiosis" },
          { href: "/graph", label: "Graph" },
          { href: "/esg", label: "ESG" },
        ]
    : [];

  return (
    <nav className="navbar">
      <div className="navbar-inner">
        <Link href="/" className="brand">
          ReCircle
        </Link>
        <div className="nav-links">
          {links.map((link) => (
            <Link key={link.href} href={link.href}>
              {link.label}
            </Link>
          ))}
        </div>
        <div className="nav-user">
          {user ? (
            <>
              <span className="nav-role">
                {user.full_name} &middot; {user.role} &middot; {user.organization?.name}
              </span>
              <button type="button" className="btn btn-ghost" onClick={handleLogout}>
                Log out
              </button>
            </>
          ) : (
            <Link href="/login" className="btn btn-ghost">
              Log in
            </Link>
          )}
        </div>
      </div>
    </nav>
  );
}
