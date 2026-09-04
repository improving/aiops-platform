"use client";

import ModelDetails from "@/components/models/ModelDetails";
import Dashboard from "@/components/Dashboard";

export default function ModelDetailsPage({
  params,
}: {
  params: { id: string };
}) {
  return (
    <Dashboard title="Model Details">
      <ModelDetails params={params} />
    </Dashboard>
  );
}