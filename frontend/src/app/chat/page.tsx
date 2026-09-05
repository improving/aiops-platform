"use client";

import { Suspense } from "react";
import ChatPanel from "@/components/chat/ChatPanel";
import Dashboard from "@/components/Dashboard";

export default function ChatRoute() {
  return (
    <Dashboard title="Chat">
      <Suspense>
        <ChatPanel />
      </Suspense>
    </Dashboard>
  );
}
