"use client";

import React from "react";
import { LANGFLOW_URL } from "@/constants";
import NotConfigured from "@/components/NotConfigured";

export default function Develop() {
  if (!LANGFLOW_URL) {
    return <NotConfigured name="Langflow" envVar="NEXT_PUBLIC_LANGFLOW_URL" />;
  }

  return (
    <div className="flex justify-center items-center h-screen">
      <iframe
        src={LANGFLOW_URL}
        className="w-full h-full"
        title="Develop Environment"
        frameBorder="0"
        allowFullScreen
      />
    </div>
  );
}
