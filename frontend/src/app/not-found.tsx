"use client";

import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import Dashboard from "@/components/Dashboard";

export default function NotFound() {
  const router = useRouter();

  return (
    <Dashboard title="Page not found">
      <div className="flex flex-col items-center gap-4 py-16 text-center">
        <p className="text-muted-foreground">
          We could not find the page you were looking for.
        </p>
        <Button onClick={() => router.push("/")}>Back to home</Button>
      </div>
    </Dashboard>
  );
}
