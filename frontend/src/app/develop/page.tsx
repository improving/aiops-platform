"use client";

import Develop from "@/components/develop/Develop";
import Dashboard from "@/components/Dashboard";
import { LANGFLOW_URL } from "@/constants";

export default function DevelopPage() {
  return (
    <Dashboard
      title="Interactively Develop AI Applications"
      iconUrl={LANGFLOW_URL}
      fill
    >
      <Develop />
    </Dashboard>
  );
}
