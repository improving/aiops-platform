import NextAuth from "next-auth";
import type { JWT } from "next-auth/jwt";
import Keycloak from "next-auth/providers/keycloak";

// Keycloak is the only identity source. The UI is the public client
// `aiops-ui` (PKCE, no secret); the tokens it receives are kept inside the
// encrypted Auth.js session cookie and never reach the browser as cookies of
// their own. The proxy forwards the access token to the backend as a bearer.

const issuer = process.env.AUTH_KEYCLOAK_ISSUER ?? "";
const clientId = process.env.AUTH_KEYCLOAK_ID ?? "aiops-ui";

export const REFRESH_ERROR = "RefreshAccessTokenError";

declare module "next-auth" {
  interface Session {
    /** Keycloak access token; the proxy sends it to the backend. */
    accessToken?: string;
    /** Keycloak ID token; `end_session_endpoint` wants it as a hint. */
    idToken?: string;
    /** Realm roles from the access token. UI hints only, never authorization. */
    roles: string[];
    /** Set when the refresh token was rejected; the user has to sign in again. */
    error?: typeof REFRESH_ERROR;
    /** Keycloak logout URL that ends the SSO session and returns to /login. */
    endSessionUrl?: string;
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    access_token?: string;
    refresh_token?: string;
    id_token?: string;
    /** Access token expiry, seconds since the epoch. */
    expires_at?: number;
    error?: typeof REFRESH_ERROR;
  }
}

/** Public JWT claims Keycloak puts in an access token. */
type AccessTokenClaims = {
  realm_access?: { roles?: string[] };
};

// The backend verifies the signature; here the payload is only read for
// UI hints, so decoding without verification is fine.
export function decodeJwtPayload(token: string): AccessTokenClaims | null {
  const segment = token.split(".")[1];
  if (!segment) return null;
  try {
    return JSON.parse(Buffer.from(segment, "base64url").toString("utf8"));
  } catch {
    return null;
  }
}

export function realmRoles(accessToken: string | undefined): string[] {
  if (!accessToken) return [];
  return decodeJwtPayload(accessToken)?.realm_access?.roles ?? [];
}

// Keycloak ends the SSO session at end_session_endpoint. `id_token_hint`
// identifies the session and the client, so Keycloak can validate the
// post-logout redirect against the client's allowed list. `client_id` is
// sent as well so the redirect is still accepted when the hint is missing.
export function endSessionUrl(idToken: string | undefined): string | undefined {
  if (!issuer) return undefined;
  const url = new URL(`${issuer}/protocol/openid-connect/logout`);
  const authUrl = process.env.AUTH_URL ?? "http://localhost:3000";
  url.searchParams.set(
    "post_logout_redirect_uri",
    `${authUrl.replace(/\/$/, "")}/login`
  );
  url.searchParams.set("client_id", clientId);
  if (idToken) url.searchParams.set("id_token_hint", idToken);
  return url.toString();
}

type RefreshResponse = {
  access_token: string;
  refresh_token?: string;
  id_token?: string;
  expires_in: number;
};

async function refreshAccessToken(token: JWT): Promise<JWT> {
  if (!token.refresh_token) {
    return { ...token, error: REFRESH_ERROR };
  }
  try {
    const response = await fetch(`${issuer}/protocol/openid-connect/token`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        grant_type: "refresh_token",
        client_id: clientId,
        refresh_token: token.refresh_token,
      }),
    });
    if (!response.ok) {
      // Keycloak answers {error, error_description}; both are safe to log.
      const body = (await response.text()).slice(0, 200);
      console.warn(
        `auth: token refresh failed with ${response.status}: ${body}`
      );
      return { ...token, error: REFRESH_ERROR };
    }
    const refreshed = (await response.json()) as RefreshResponse;
    return {
      ...token,
      access_token: refreshed.access_token,
      // Keycloak rotates the refresh token when the realm says so; keep the
      // old one otherwise.
      refresh_token: refreshed.refresh_token ?? token.refresh_token,
      id_token: refreshed.id_token ?? token.id_token,
      expires_at: Math.floor(Date.now() / 1000) + refreshed.expires_in,
      error: undefined,
    };
  } catch (error) {
    console.warn("auth: token refresh failed", error);
    return { ...token, error: REFRESH_ERROR };
  }
}

// Refresh a little before the access token expires, so a request that is in
// flight at the boundary does not reach the backend with a stale token.
const REFRESH_SKEW_SECONDS = 30;

export const { handlers, auth, signIn, signOut } = NextAuth({
  // AUTH_URL is set explicitly in every environment; trustHost keeps Auth.js
  // from second-guessing the host behind the dev server or a container.
  trustHost: true,
  providers: [
    Keycloak({
      issuer,
      clientId,
      // Public client: PKCE instead of a secret, and no client
      // authentication on the token endpoint.
      checks: ["pkce"],
      client: { token_endpoint_auth_method: "none" },
    }),
  ],
  session: { strategy: "jwt" },
  pages: { signIn: "/login" },
  callbacks: {
    async jwt({ token, account }) {
      if (account) {
        // First sign-in: keep everything the proxy and the logout need.
        return {
          ...token,
          access_token: account.access_token,
          refresh_token: account.refresh_token,
          id_token: account.id_token,
          expires_at: account.expires_at,
          error: undefined,
        };
      }
      const now = Math.floor(Date.now() / 1000);
      if (token.expires_at && now < token.expires_at - REFRESH_SKEW_SECONDS) {
        return token;
      }
      return refreshAccessToken(token);
    },
    async session({ session, token }) {
      session.accessToken = token.access_token;
      session.idToken = token.id_token;
      session.roles = realmRoles(token.access_token);
      session.error = token.error;
      session.endSessionUrl = endSessionUrl(token.id_token);
      return session;
    },
  },
});
