"use client";

import ModelFineTune from "@/components/models/ModelFineTune";
import Dashboard from "@/components/Dashboard";

export default function ModelFineTunePage({
  params,
}: {
  params: { id: string };
}) {
  return (
    <Dashboard title="Fine-tune Model">
      <ModelFineTune params={params} />
    </Dashboard>
  );
}