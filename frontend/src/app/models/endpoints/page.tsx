"use client";

import InferenceEndpoints from "@/components/models/InferenceEndpoints";
import Dashboard from "@/components/Dashboard";

export default function InferenceEndpointsPage() {
  return (
    <Dashboard title="Model Instances">
      <InferenceEndpoints />
    </Dashboard>
  );
}
