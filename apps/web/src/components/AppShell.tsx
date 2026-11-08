"use client";

import { LogOut, Menu, X } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { navFor } from "@/lib/navigation";
import { useSession, useSignedIn } from "@/lib/session";
import { ROLE_LABELS } from "@/lib/types";

import styles from "./AppShell.module.css";

export function AppShell({ children }: { children: React.ReactNode }) {
  const { user, school } = useSignedIn();
  const { signOut } = useSession();
  const pathname = usePathname();
  const router = useRouter();
  const [menuOpen, setMenuOpen] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const groups = navFor(user.role);

  // Close the phone menu after navigating.
  useEffect(() => setMenuOpen(false), [pathname]);

  async function onSignOut() {
    setSigningOut(true);
    try {
      await signOut();
    } finally {
      router.replace("/sign-in");
    }
  }

  return (
    <div className={styles.shell}>
      <header className={styles.topbar}>
        <button
          type="button"
          className={`btn btn-ghost ${styles.menuButton}`}
          aria-label={menuOpen ? "Close menu" : "Open menu"}
          aria-expanded={menuOpen}
          aria-controls="main-navigation"
          onClick={() => setMenuOpen((open) => !open)}
        >
          {menuOpen ? <X size={20} /> : <Menu size={20} />}
        </button>
        <Link href="/dashboard" className={styles.brand}>
          <span className={styles.mark} aria-hidden="true">
            C
          </span>
          <span className={styles.schoolName}>{school.name}</span>
        </Link>
        <div className={styles.who}>
          <span className={styles.person}>
            <strong>{user.display_name}</strong>
            <span className="muted">
              {ROLE_LABELS[user.role]}
              {user.is_exam_coordinator ? " · Exam coordinator" : ""}
            </span>
          </span>
          <button type="button" className="btn btn-secondary" onClick={onSignOut} disabled={signingOut}>
            <LogOut size={16} aria-hidden="true" />
            <span className={styles.signOutLabel}>{signingOut ? "Signing out…" : "Sign out"}</span>
          </button>
        </div>
      </header>
      <div className={styles.body}>
        <nav
          id="main-navigation"
          aria-label="Main"
          className={`${styles.nav} ${menuOpen ? styles.navOpen : ""}`}
        >
          {groups.map((group, index) => (
            <div key={group.label ?? index} className={styles.navGroup}>
              {group.label && <span className={styles.navLabel}>{group.label}</span>}
              {group.items.map(({ href, label, icon: Icon }) => {
                const active = pathname === href || pathname.startsWith(`${href}/`);
                return (
                  <Link
                    key={href}
                    href={href}
                    className={`${styles.navLink} ${active ? styles.active : ""}`}
                    aria-current={active ? "page" : undefined}
                  >
                    <Icon size={18} aria-hidden="true" />
                    {label}
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>
        <main className={styles.content}>{children}</main>
      </div>
    </div>
  );
}
