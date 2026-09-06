"use client";

import { useEffect, useState } from "react";
import { AxiosError } from "axios";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { LoadingState } from "@/components/LoadingState";
import { Skeleton } from "@/components/ui/skeleton";
import { modelService } from "@/services/modelService";
import { vectorDBService } from "@/services/vectorDBService";
import { notebookService } from "@/services/notebookService";
import { ChatBubbleIcon, PlusIcon, RocketIcon } from "@radix-ui/react-icons";

type Stat = { ready: number; total: number };
type Stats = {
  instances: Stat | null;
  vectordbs: Stat | null;
  notebooks: Stat | null;
  chat: Stat | null;
};
type StatMessages = Partial<Record<keyof Stats, string>>;

function count<T extends { ready: boolean }>(items: T[] | null): Stat | null {
  return items === null
    ? null
    : { ready: items.filter((i) => i.ready).length, total: items.length };
}

// A tile whose list failed shows "unavailable" (with the HTTP status when the
// rejection was an AxiosError carrying one) instead of blanking the page.
function unavailableText(reason: unknown): string {
  if (reason instanceof AxiosError && reason.response?.status) {
    return `unavailable (HTTP ${reason.response.status})`;
  }
  return "unavailable";
}

function StatTile({
  id,
  title,
  stat,
  href,
  showTotal,
  unavailable,
}: {
  id: keyof Stats;
  title: string;
  stat: Stat | null;
  href: string;
  showTotal: boolean;
  unavailable?: string;
}) {
  return (
    <Link
      href={href}
      className="rounded-xl border p-4 hover:bg-accent"
      data-testid={`home-stat-${id}`}
    >
      <p className="text-sm text-muted-foreground">{title}</p>
      {stat === null ? (
        <p className="text-2xl font-bold">{unavailable ?? "unavailable"}</p>
      ) : (
        <>
          <p className="text-2xl font-bold">{stat.ready} ready</p>
          {showTotal && (
            <p className="text-sm text-muted-foreground">{stat.total} total</p>
          )}
        </>
      )}
    </Link>
  );
}

export function HomeOverview() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [unavailable, setUnavailable] = useState<StatMessages>({});

  useEffect(() => {
    // Each list fails independently (a 503 on one must not blank the rest).
    Promise.allSettled([
      modelService.getInferenceInstances(),
      vectorDBService.getVectorDBInstances(),
      notebookService.getNotebooks(),
      modelService.getChatTargets(),
    ])
      .then(([inst, vdb, nb, targets]) => {
        const list = <T,>(name: keyof Stats, r: PromiseSettledResult<T[]>) => {
          if (r.status === "fulfilled") return r.value;
          console.error(`home overview: ${name} failed`, r.reason);
          return null;
        };
        const instList = list("instances", inst);
        const vdbList = list("vectordbs", vdb);
        const nbList = list("notebooks", nb);
        const targetsList = list("chat", targets);
        const chat =
          targetsList === null
            ? null
            : targetsList.filter((t) => t.capability === "chat");
        setStats({
          instances: count(instList),
          vectordbs: count(vdbList),
          notebooks: count(nbList),
          chat: count(chat),
        });
        setUnavailable({
          instances:
            inst.status === "rejected"
              ? unavailableText(inst.reason)
              : undefined,
          vectordbs:
            vdb.status === "rejected" ? unavailableText(vdb.reason) : undefined,
          notebooks:
            nb.status === "rejected" ? unavailableText(nb.reason) : undefined,
          chat:
            targets.status === "rejected"
              ? unavailableText(targets.reason)
              : undefined,
        });
      })
      .catch((reason) => {
        // Promise.allSettled itself never rejects, but a defensive net keeps
        // the page from staying on the skeleton forever if it ever does.
        console.error("home overview: failed to load stats", reason);
        setStats({
          instances: null,
          vectordbs: null,
          notebooks: null,
          chat: null,
        });
      });
  }, []);

  return (
    <section className="mb-8 space-y-4">
      {stats ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatTile
            id="instances"
            title="Model instances"
            stat={stats.instances}
            href="/models/endpoints"
            showTotal
            unavailable={unavailable.instances}
          />
          <StatTile
            id="vectordbs"
            title="Vector databases"
            stat={stats.vectordbs}
            href="/vector-databases/endpoints"
            showTotal
            unavailable={unavailable.vectordbs}
          />
          <StatTile
            id="notebooks"
            title="Notebooks"
            stat={stats.notebooks}
            href="/notebooks"
            showTotal
            unavailable={unavailable.notebooks}
          />
          <StatTile
            id="chat"
            title="Chat targets"
            stat={stats.chat}
            href="/chat"
            showTotal={false}
            unavailable={unavailable.chat}
          />
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
