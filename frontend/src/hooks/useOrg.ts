"use client";

import { useCallback, useEffect, useState } from "react";
import { orgService } from "@/services/orgService";
import type { CurrentOrganization, OrgRole } from "@/types/organization";

/**
 * The caller's active organization and role, from
 * GET /v1alpha1/organizations/current. Menu visibility follows the
 * membership role (and `is_platform_admin`), not the realm role; the
 * backend enforces either way. No session is needed: the proxy adds the
 * bearer and the `X-Org` header.
 */
export function useOrg(): {
  org: CurrentOrganization | null;
  role: OrgRole | null;
  isAdmin: boolean;
  isPlatformAdmin: boolean;
  loading: boolean;
  refresh: () => Promise<void>;
} {
  const [org, setOrg] = useState<CurrentOrganization | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      setOrg(await orgService.getCurrent());
    } catch {
      // A 403 for a stale cookie is handled by the axios interceptor
      // (services/api.ts); anything else leaves the block hidden.
      setOrg(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    (async () => {
      await refresh();
    })();
  }, [refresh]);

  return {
    org,
    role: org?.role ?? null,
    isAdmin: org?.role === "admin",
    isPlatformAdmin: org?.is_platform_admin ?? false,
    loading,
    refresh,
  };
}
