import type { Session } from "next-auth";
import { AUTH_DISABLED } from "@/constants";

/**
 * Whether the signed-in user may perform admin-only writes (providers,
 * budgets, ...). `AUTH_MODE=disabled` treats every caller as admin, the
 * same way the backend does (`auth/current_user.py`); otherwise the realm
 * role "admin" must be present on the session. UI hint only, like
 * `session.roles` itself -- the backend enforces this either way.
 */
export function isAdmin(session: Session | null | undefined): boolean {
  if (AUTH_DISABLED) return true;
  return !!session?.roles?.includes("admin");
}
