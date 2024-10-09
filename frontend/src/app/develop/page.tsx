"use client";

import Develop from "@/components/develop/Develop";
import Dashboard from "@/components/Dashboard";

export default function DevelopPage() {
  return (
    <Dashboard title="Interactively Develop AI Applications" iconUrl={ process.env.LANGFLOW_URL ||
                    "http://192.0.2.211:8080" }>
      <Develop />
    </Dashboard>
  );
}
