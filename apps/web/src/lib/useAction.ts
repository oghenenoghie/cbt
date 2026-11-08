"use client";

import { useCallback, useState } from "react";

import { ApiError } from "@/lib/api";
import { useSession } from "@/lib/session";

/**
 * Run a change against the API with a busy flag and the error to show. `run` resolves to true
 * when the change worked. A 401 re-checks the session, which sends the person to sign in.
 */
export function useAction() {
  const { refresh } = useSession();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  const run = useCallback(
    async (change: () => Promise<unknown>): Promise<boolean> => {
      setBusy(true);
      setError(null);
      try {
        await change();
        return true;
      } catch (caught) {
        const apiError =
          caught instanceof ApiError ? caught : new ApiError(0, "Something went wrong. Try again.");
        if (apiError.status === 401) void refresh();
        setError(apiError);
        return false;
      } finally {
        setBusy(false);
      }
    },
    [refresh],
  );

  const clearError = useCallback(() => setError(null), []);
  return { busy, error, run, clearError };
}
