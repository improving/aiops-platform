"use client";

import Develop from "@/components/develop/Develop";
import Dashboard from "@/components/Dashboard";

export default function DevelopPage() {
  return (
    <Dashboard title="Interactively Develop AI Applications" iconUrl="http://192.0.2.211:8080/">
      <Develop />
    </Dashboard>
  );
}
