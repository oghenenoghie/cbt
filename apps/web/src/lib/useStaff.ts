"use client";

import { useEffect, useState } from "react";

import { ApiError, listAllUsers } from "@/lib/api";
import { useSession } from "@/lib/session";
import type { Account } from "@/lib/types";
import type { Loadable } from "@/lib/useApi";

/**
 * Active teachers and school admins, by name: anyone on the staff can be assigned to teach or head
 * a department. Only school admins can list accounts.
 */
export function useStaff(): Loadable<Account[]> & { reload: () => void } {
  const { refresh } = useSession();
  const [state, setState] = useState<Loadable<Account[]>>({ status: "loading" });
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      listAllUsers<Account>({ role: "teacher", status: "active" }),
      listAllUsers<Account>({ role: "school_admin", status: "active" }),
    ])
      .then(([teachers, admins]) => {
        if (cancelled) return;
        const staff = [...teachers, ...admins].sort((a, b) => a.display_name.localeCompare(b.display_name));
        setState({ status: "ready", data: staff });
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        if (error instanceof ApiError && error.status === 401) void refresh();
        setState({
          status: "error",
          message: error instanceof ApiError ? error.message : "Something went wrong.",
        });
      });
    return () => {
      cancelled = true;
    };
  }, [version, refresh]);

  return { ...state, reload: () => setVersion((v) => v + 1) };
}
