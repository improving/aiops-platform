"use client";

import InferenceEndpoints from "@/components/models/InferenceEndpoints";
import Dashboard from "@/components/Dashboard";

export default function InferenceEndpointsPage() {
  return (
    <Dashboard title="Inference Endpoints">
      <InferenceEndpoints />
    </Dashboard>
  );
}
