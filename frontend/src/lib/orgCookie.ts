// The active organization travels as the `aiops_org` cookie (set by the
// switcher) and reaches the backend as the `X-Org` header (src/proxy.ts,
// src/app/api/chat/route.ts). `aiops_dev_user` is honoured only when
// AUTH_MODE=disabled and becomes `X-Dev-User` (backend/auth/dev_users.py).

export const ORG_COOKIE = "aiops_org";
export const DEV_USER_COOKIE = "aiops_dev_user";
export const ORG_HEADER = "X-Org";
export const DEV_USER_HEADER = "X-Dev-User";
/** backend/auth/current_user.py NOT_A_MEMBER, verbatim. */
export const NOT_A_MEMBER = "You are not a member of this organization";

const ONE_YEAR_SECONDS = 60 * 60 * 24 * 365;

export function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const prefix = `${name}=`;
  const found = document.cookie
    .split("; ")
    .find((part) => part.startsWith(prefix));
  return found ? decodeURIComponent(found.slice(prefix.length)) : null;
}

export function readOrgCookie(): string | null {
  return readCookie(ORG_COOKIE);
}

/** Path `/`, SameSite Lax, one year (spec 5.5); Secure over https. */
export function setOrgCookie(slug: string) {
  const secure = location.protocol === "https:" ? "; Secure" : "";
  document.cookie = `${ORG_COOKIE}=${encodeURIComponent(slug)}; Path=/; Max-Age=${ONE_YEAR_SECONDS}; SameSite=Lax${secure}`;
}

export function clearOrgCookie() {
  document.cookie = `${ORG_COOKIE}=; Path=/; Max-Age=0; SameSite=Lax`;
}
