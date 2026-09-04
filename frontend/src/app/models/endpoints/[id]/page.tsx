"use client";

import InferenceEndpointDetails from "@/components/models/InferenceEndpointDetails";
import Dashboard from "@/components/Dashboard";

export default function InferenceEndpointDetailsPage({
  params,
}: {
  params: { id: string };
}) {
  return (
    <Dashboard title="Inference Endpoint Details">
      <InferenceEndpointDetails params={params} />
    </Dashboard>
  );
}
