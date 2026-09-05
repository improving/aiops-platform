"use client";

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { signIn } from "next-auth/react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

// Only same-site paths; anything else goes back to the home page.
function safeCallbackUrl(value: string | null): string {
  return value && value.startsWith("/") && !value.startsWith("//")
    ? value
    : "/";
}

// signIn runs on the client on purpose: Auth.js issue #13388 makes the
// server-action variant fail on Next 16 when x-forwarded-proto is missing.
function LoginForm() {
  const searchParams = useSearchParams();
  const [loading, setLoading] = useState(false);
  const redirectTo = safeCallbackUrl(searchParams.get("callbackUrl"));

  const onClick = async () => {
    setLoading(true);
    await signIn("keycloak", { redirectTo });
  };

  return (
    <Button onClick={onClick} loading={loading} className="w-full">
      Sign in with Keycloak
    </Button>
  );
}

export default function LoginPage() {
  return (
    <main className="flex min-h-screen items-center justify-center px-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle className="text-2xl">AI Hub</CardTitle>
          <CardDescription>
            Sign in with your platform account to continue.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Suspense
            fallback={
              <Button className="w-full" disabled>
                Sign in with Keycloak
              </Button>
            }
          >
            <LoginForm />
          </Suspense>
        </CardContent>
      </Card>
    </main>
  );
}
