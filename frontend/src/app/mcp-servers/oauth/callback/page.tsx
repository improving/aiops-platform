"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import Dashboard from "@/components/Dashboard";
import { OAUTH_RETURN_KEY } from "@/components/mcp/ConnectCredentialDialog";
import { parseApiError } from "@/lib/utils";
import { mcpService } from "@/services/mcpService";

/**
 * Where an MCP server's authorization server sends the browser back
 * after a sign-in. A page and not an API path: without a session a page
 * goes to the login and comes back here. The code is in this page's URL
 * (PKCE and one use make a copy of it worthless) and goes on to the
 * backend in a body. It hands `code` and `state` to the
 * backend, which checks that this member started the sign-in, and then
 * returns to where the member was.
 */
function Callback() {
  const params = useSearchParams();
  const router = useRouter();
  const [problem, setProblem] = useState<string | null>(null);
  // Strict mode mounts twice, and a code can be used once.
  const sent = useRef(false);

  useEffect(() => {
    if (sent.current) return;
    sent.current = true;
    (async () => {
      const code = params.get("code");
      const state = params.get("state");
      if (!code || !state) {
        // Shown as text, never as markup: it comes from another site.
        setProblem(
          params.get("error_description") ||
            params.get("error") ||
            "The sign-in did not finish."
        );
        return;
      }
      try {
        const server = await mcpService.finishSignIn(
          code,
          state,
          params.get("iss") ?? undefined
        );
        let back = "/mcp-servers";
        try {
          back = sessionStorage.getItem(OAUTH_RETURN_KEY) || back;
          sessionStorage.removeItem(OAUTH_RETURN_KEY);
        } catch {
          // The default will do.
        }
        // Only a path of this site ("/\\host" and "//host" are not).
        let path = "/mcp-servers";
        try {
          const url = new URL(back, window.location.origin);
          if (url.origin === window.location.origin)
            path = url.pathname + url.search;
        } catch {
          // The default will do.
        }
        const joiner = path.includes("?") ? "&" : "?";
        router.replace(
          `${path}${joiner}connected=${encodeURIComponent(server.name)}`
        );
      } catch (e) {
        setProblem(String(parseApiError(e).description));
      }
    })();
  }, [params, router]);

  if (problem === null) {
    return (
      <p role="status" className="text-muted-foreground">
        Finishing the sign-in…
      </p>
    );
  }
  return (
    <div className="space-y-3">
      <p role="alert" className="text-destructive">
        {problem}
      </p>
      <Link href="/mcp-servers" className="underline">
        Back to MCP servers
      </Link>
    </div>
  );
}

export default function McpOAuthCallbackPage() {
  return (
    <Dashboard title="Sign in to an MCP server">
      <Suspense>
        <Callback />
      </Suspense>
    </Dashboard>
  );
}
