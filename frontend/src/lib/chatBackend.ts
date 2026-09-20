import { createOpenAICompatible } from "@ai-sdk/openai-compatible";
import { cookies } from "next/headers";
import { auth } from "@/auth";
import { backendUrl } from "@/lib/backend";
import {
  DEV_USER_COOKIE,
  DEV_USER_HEADER,
  ORG_COOKIE,
  ORG_HEADER,
} from "@/lib/orgCookie";

/**
 * What the chat route handlers (`/api/chat`, `/api/chat/compact`) share:
 * the caller's identity as headers for the backend, and the model
 * provider on the backend's OpenAI-compatible endpoint. Server only.
 * Both handlers are excluded from the proxy matcher, so they forward the
 * bearer, the organization and (in disabled mode) the dev user
 * themselves, the same way `src/proxy.ts` does for `/api/v1alpha1/*`.
 */

export function authDisabled(): boolean {
  return process.env.AUTH_MODE === "disabled";
}

async function accessToken(): Promise<string | undefined> {
  if (authDisabled()) return undefined;
  const session = await auth();
  // A session whose refresh was rejected is as good as none (src/proxy.ts).
  if (!session || session.error) return undefined;
  return session.accessToken;
}

/** The headers of the caller, or null when nobody is signed in. */
export async function backendHeaders(): Promise<Record<string, string> | null> {
  const token = await accessToken();
  if (!token && !authDisabled()) return null;
  const headers: Record<string, string> = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  const jar = await cookies();
  const org = jar.get(ORG_COOKIE)?.value;
  if (org) headers[ORG_HEADER] = org;
  const devUser = authDisabled() ? jar.get(DEV_USER_COOKIE)?.value : undefined;
  if (devUser) headers[DEV_USER_HEADER] = devUser;
  return headers;
}

export function chatProvider(headers: Record<string, string>) {
  return createOpenAICompatible({
    name: "aiops",
    baseURL: `${backendUrl()}/v1alpha1`,
    headers,
    // `stream_options.include_usage`: the last chunk carries the token
    // counts the speed line and the context meter show.
    includeUsage: true,
  });
}
