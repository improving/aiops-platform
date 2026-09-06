"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { LoadingState } from "@/components/LoadingState";
import { Skeleton } from "@/components/ui/skeleton";
import { modelService } from "@/services/modelService";
import { vectorDBService } from "@/services/vectorDBService";
import { notebookService } from "@/services/notebookService";
import { ChatBubbleIcon, PlusIcon, RocketIcon } from "@radix-ui/react-icons";

type Stat = { ready: number; total: number };
type Stats = { instances: Stat; vectordbs: Stat; notebooks: Stat; chat: Stat };

function count<T extends { ready?: boolean }>(items: T[]): Stat {
  return { ready: items.filter((i) => i.ready).length, total: items.length };
}

function StatTile({ id, title, stat, href }: { id: string; title: string; stat: Stat; href: string }) {
  return (
    <Link href={href} className="rounded-xl border p-4 hover:bg-accent" data-testid={`home-stat-${id}`}>
      <p className="text-sm text-muted-foreground">{title}</p>
      <p className="text-2xl font-bold">{stat.ready} ready</p>
      {id !== "chat" && <p className="text-sm text-muted-foreground">{stat.total} total</p>}
    </Link>
  );
}

export function HomeOverview() {
  const [stats, setStats] = useState<Stats | null>(null);

  useEffect(() => {
    // Each list fails independently (a 503 on one must not blank the rest).
    Promise.allSettled([
      modelService.getInferenceInstances(),
      vectorDBService.getVectorDBInstances(),
      notebookService.getNotebooks(),
      modelService.getChatTargets(),
    ]).then(([inst, vdb, nb, targets]) => {
      const list = <T,>(r: PromiseSettledResult<T[]>) => (r.status === "fulfilled" ? r.value : []);
      const chat = list(targets).filter((t) => t.capability === "chat");
      setStats({
        instances: count(list(inst)),
        vectordbs: count(list(vdb)),
        notebooks: count(list(nb)),
        chat: { ready: chat.filter((t) => t.ready).length, total: chat.length },
      });
    });
  }, []);

  return (
    <section className="mb-8 space-y-4">
      {stats ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatTile id="instances" title="Model instances" stat={stats.instances} href="/models/endpoints" />
          <StatTile id="vectordbs" title="Vector databases" stat={stats.vectordbs} href="/vector-databases/endpoints" />
          <StatTile id="notebooks" title="Notebooks" stat={stats.notebooks} href="/notebooks" />
          <StatTile id="chat" title="Chat targets" stat={stats.chat} href="/chat" />
        </div>
      ) : (
        <LoadingState>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-24 rounded-xl" />
            ))}
          </div>
        </LoadingState>
      )}
      <div className="flex flex-wrap gap-2">
        <Button asChild>
          <Link href="/models/catalog">
            <RocketIcon className="h-4 w-4" />
            Launch a model
          </Link>
        </Button>
        <Button asChild variant="secondary">
          <Link href="/notebooks/new">
            <PlusIcon className="h-4 w-4" />
            New notebook
          </Link>
        </Button>
        <Button asChild variant="secondary">
          <Link href="/chat">
            <ChatBubbleIcon className="h-4 w-4" />
            Open chat
          </Link>
        </Button>
      </div>
    </section>
  );
}
