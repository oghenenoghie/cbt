"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback } from "react";

/**
 * Selections kept in the address (e.g. `?session=…&arm=…`), so a link or a reload opens the same
 * class. Pages that use this must sit inside <Suspense>.
 */
export function useQueryParams(): {
  get: (name: string) => string | null;
  update: (changes: Record<string, string | null>) => void;
} {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();

  const get = useCallback((name: string) => params.get(name), [params]);
  const update = useCallback(
    (changes: Record<string, string | null>) => {
      const next = new URLSearchParams(params.toString());
      for (const [name, value] of Object.entries(changes)) {
        if (value) next.set(name, value);
        else next.delete(name);
      }
      const query = next.toString();
      router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
    },
    [params, pathname, router],
  );
  return { get, update };
}
