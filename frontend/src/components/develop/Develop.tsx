"use client";

import React from "react";
import { LANGFLOW_URL } from "@/constants";
import NotConfigured from "@/components/NotConfigured";

export default function Develop() {
  if (!LANGFLOW_URL) {
    return <NotConfigured name="Langflow" envVar="NEXT_PUBLIC_LANGFLOW_URL" />;
  }

  return (
    <div className="flex h-screen flex-col">
      {/* Keycloak's login page refuses to render inside a frame
          (frame-ancestors 'self'), so an expired gateway session for the
          Langflow host shows "refused to connect" here until the user
          signs in on that host in a top-level tab. */}
      <p className="mb-2 text-sm text-muted-foreground">
        If the embedded editor shows &quot;refused to connect&quot;, the
        Langflow session has expired:{" "}
        <a
          href={LANGFLOW_URL}
          target="_blank"
          rel="noreferrer"
          className="underline"
        >
          open Langflow in a new tab
        </a>
        , sign in, then reload this page.
      </p>
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
