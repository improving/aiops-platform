"use client";

import LaunchModel from "@/components/models/LaunchModel";
import Dashboard from "@/components/Dashboard";

export default function LaunchModelPage({
  params,
}: {
  params: { id: string };
}) {
  return (
    <Dashboard title="Launch Model">
      <LaunchModel params={params} />
    </Dashboard>
  );
}
