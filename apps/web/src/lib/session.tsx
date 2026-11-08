"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { api, ApiError, setCsrfToken } from "@/lib/api";
import type { SessionInfo } from "@/lib/types";

type SessionState =
  | { status: "loading" }
  | { status: "signed-out" }
  | { status: "signed-in"; session: SessionInfo };

interface SessionContextValue {
  state: SessionState;
  signIn(schoolCode: string, username: string, password: string): Promise<SessionInfo>;
  signOut(): Promise<void>;
  /** Re-read the session, for example after the API reports it has ended (401). */
  refresh(): Promise<void>;
}

const SessionContext = createContext<SessionContextValue | null>(null);

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<SessionState>({ status: "loading" });

  const accept = useCallback((session: SessionInfo) => {
    setCsrfToken(session.csrf_token);
    setState({ status: "signed-in", session });
  }, []);

  const forget = useCallback(() => {
    setCsrfToken(null);
    setState({ status: "signed-out" });
  }, []);

  const refresh = useCallback(async () => {
    try {
      accept(await api<SessionInfo>("/auth/me"));
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) forget();
      else throw error;
    }
  }, [accept, forget]);

  useEffect(() => {
    refresh().catch(() => setState({ status: "signed-out" }));
  }, [refresh]);

  const signIn = useCallback(
    async (schoolCode: string, username: string, password: string) => {
      const session = await api<SessionInfo>("/auth/login", {
        method: "POST",
        body: { school_code: schoolCode, username, password },
      });
      accept(session);
      return session;
    },
    [accept],
  );

  const signOut = useCallback(async () => {
    try {
      await api("/auth/logout", { method: "POST" });
    } finally {
      forget();
    }
  }, [forget]);

  const value = useMemo(() => ({ state, signIn, signOut, refresh }), [state, signIn, signOut, refresh]);
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionContextValue {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useSession must be used inside <SessionProvider>.");
  return value;
}

/** The signed-in school user. Only use inside the signed-in part of the app. */
export function useSignedIn(): SessionInfo & { user: NonNullable<SessionInfo["user"]>; school: NonNullable<SessionInfo["school"]> } {
  const { state } = useSession();
  if (state.status !== "signed-in" || !state.session.user || !state.session.school) {
    throw new Error("useSignedIn is only available to signed-in school users.");
  }
  return state.session as ReturnType<typeof useSignedIn>;
}
