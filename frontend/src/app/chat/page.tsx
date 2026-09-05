"use client";

import { Suspense } from "react";
import { useSession } from "next-auth/react";
import ChatPanel from "@/components/chat/ChatPanel";
import Dashboard from "@/components/Dashboard";
import { AUTH_DISABLED } from "@/constants";

// AUTH_MODE=disabled mounts no SessionProvider, so useSession() must not
// be called in that mode; the split keeps the hook out of that path.
function ChatWithSession() {
  const { data: session } = useSession();
  const userKey = session?.user?.email ?? session?.user?.name ?? "anonymous";
  return <ChatPanel userKey={userKey} />;
}

export default function ChatRoute() {
  return (
    <Dashboard title="Chat">
      <Suspense>
        {AUTH_DISABLED ? <ChatPanel userKey="dev" /> : <ChatWithSession />}
      </Suspense>
    </Dashboard>
  );
}
