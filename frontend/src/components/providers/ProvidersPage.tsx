"use client";

import { Fragment, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Switch } from "@/components/ui/switch";
import { ChevronDownIcon, ChevronRightIcon } from "@radix-ui/react-icons";
import { useToast } from "@/components/hooks/use-toast";
import { parseApiError } from "@/lib/utils";
import { providerService } from "@/services/providerService";
import type { Provider } from "@/types/models";
import { DeleteButton } from "@/components/DeleteButton";
import { AddProviderDialog } from "@/components/providers/AddProviderDialog";
import { BudgetCard } from "@/components/providers/BudgetCard";

const CAPABILITY_LABEL: Record<string, string> = {
  chat: "Chat",
  embedding: "Embedding",
};

function formatPrice(value: number | null): string {
  if (value === null) return "—";
  // Providers quote per-token prices in fractions of a cent; show the unit
  // people actually compare, price per one million tokens.
  return `$${(value * 1_000_000).toFixed(2)} / 1M tok`;
}

interface ProvidersPageProps {
  /**
   * Whether the caller may add or change providers, budgets and models.
   * Resolved by the route (`app/providers/page.tsx`), which is the one
   * place that decides whether it is even safe to call `useSession()`
   * (there is no `SessionProvider` when `AUTH_MODE=disabled`, see
   * `AuthProvider.tsx`) -- a UI hint only, like `session.roles` itself,
   * since the backend enforces `require_admin` regardless.
   */
  admin: boolean;
}

export default function ProvidersPage({ admin }: ProvidersPageProps) {
  const { toast } = useToast();
  const [providers, setProviders] = useState<Provider[]>([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [addOpen, setAddOpen] = useState(false);

  const fetchProviders = useCallback(async () => {
    try {
      const data = await providerService.getProviders();
      setProviders(data);
    } catch (error) {
      toast(parseApiError(error));
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    fetchProviders();
  }, [fetchProviders]);

  const toggleExpanded = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleToggleEnabled = async (provider: Provider, enabled: boolean) => {
    try {
      const updated = await providerService.updateProvider(provider.id, {
        enabled,
      });
      setProviders((prev) =>
        prev.map((p) => (p.id === updated.id ? updated : p))
      );
    } catch (error) {
      toast(parseApiError(error));
    }
  };

  const handleDiscover = async (provider: Provider) => {
    try {
      const discovered = await providerService.discoverProviderModels(
        provider.id
      );
      const existing = new Set(provider.models.map((m) => m.model));
      const toAdd = discovered.filter((m) => !existing.has(m.id));
      if (toAdd.length === 0) {
        toast({
          title: "No new models",
          description: "Every discovered model is already added.",
        });
        return;
      }
      const displayNames = Object.fromEntries(
        toAdd.map((m) => [m.id, m.display_name])
      );
      const updated = await providerService.addModels(provider.id, {
        models: toAdd.map((m) => m.id),
        display_names: displayNames,
      });
      setProviders((prev) =>
        prev.map((p) => (p.id === updated.id ? updated : p))
      );
      toast({
        title: "Success",
        description: `Added ${toAdd.length} model(s)`,
        variant: "success",
      });
    } catch (error) {
      toast(parseApiError(error));
    }
  };

  const handleDeleteProvider = async (id: string) => {
    await providerService.deleteProvider(id);
    setProviders((prev) => prev.filter((p) => p.id !== id));
  };

  const handleRemoveModel = async (providerId: string, modelId: string) => {
    await providerService.deleteModel(providerId, modelId);
    setProviders((prev) =>
      prev.map((p) =>
        p.id === providerId
          ? { ...p, models: p.models.filter((m) => m.id !== modelId) }
          : p
      )
    );
  };

  if (loading) {
    return <div>Loading...</div>;
  }

  const columnCount = admin ? 6 : 5;

  return (
    <div className="space-y-8">
      <BudgetCard admin={admin} />

      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-semibold">Hosted providers</h2>
          <div className="flex items-center gap-4">
            {admin ? (
              <Button onClick={() => setAddOpen(true)}>Add provider</Button>
            ) : (
              <p className="text-sm text-muted-foreground">
                Only organization admins can add or change providers.
              </p>
            )}
            <Button asChild variant="outline">
              <Link href="/usage">Usage</Link>
            </Button>
          </div>
        </div>

        {providers.length === 0 ? (
          <p className="text-muted-foreground">
            No hosted providers yet.
            {admin && " Add one to expose its models to Chat."}
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead />
                <TableHead>Kind</TableHead>
                <TableHead>Name</TableHead>
                <TableHead>Models</TableHead>
                {admin && <TableHead>Enabled</TableHead>}
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {providers.map((provider) => (
                <Fragment key={provider.id}>
                  <TableRow aria-label={provider.name}>
                    <TableCell>
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label={`${provider.name} models`}
                        onClick={() => toggleExpanded(provider.id)}
                      >
                        {expanded.has(provider.id) ? (
                          <ChevronDownIcon />
                        ) : (
                          <ChevronRightIcon />
                        )}
                      </Button>
                    </TableCell>
                    <TableCell>
                      <span className="rounded-full bg-blue-100 px-2 py-1 text-sm text-blue-800">
                        {provider.kind}
                      </span>
                    </TableCell>
                    <TableCell className="font-medium">
                      {provider.name}
                    </TableCell>
                    <TableCell>{provider.models.length}</TableCell>
                    {admin && (
                      <TableCell>
                        <Switch
                          aria-label="Enabled"
                          checked={provider.enabled}
                          onCheckedChange={(checked) =>
                            handleToggleEnabled(provider, checked)
                          }
                        />
                      </TableCell>
                    )}
                    <TableCell>
                      {admin && (
                        <div className="flex gap-2">
                          <Button
                            variant="outline"
                            onClick={() => handleDiscover(provider)}
                          >
                            Discover models
                          </Button>
                          <DeleteButton
                            buttonText="Delete provider"
                            modalDescription={`Delete "${provider.name}" and every model it exposes? This cannot be undone.`}
                            onDelete={() => handleDeleteProvider(provider.id)}
                            successToastMessage="Provider deleted"
                          />
                        </div>
                      )}
                    </TableCell>
                  </TableRow>
                  {expanded.has(provider.id) && (
                    <TableRow>
                      <TableCell colSpan={columnCount}>
                        {provider.models.length === 0 ? (
                          <p className="py-2 text-sm text-muted-foreground">
                            No models exposed yet.
                          </p>
                        ) : (
                          <Table>
                            <TableHeader>
                              <TableRow>
                                <TableHead>Display name</TableHead>
                                <TableHead>Model id</TableHead>
                                <TableHead>Capability</TableHead>
                                <TableHead>Context</TableHead>
                                <TableHead>Input price</TableHead>
                                <TableHead>Output price</TableHead>
                                {admin && <TableHead />}
                              </TableRow>
                            </TableHeader>
                            <TableBody>
                              {provider.models.map((model) => (
                                <TableRow key={model.id}>
                                  <TableCell>{model.display_name}</TableCell>
                                  <TableCell>{model.model}</TableCell>
                                  <TableCell>
                                    {CAPABILITY_LABEL[model.capability] ??
                                      model.capability}
                                  </TableCell>
                                  <TableCell>
                                    {model.context_length ?? "—"}
                                  </TableCell>
                                  <TableCell>
                                    {formatPrice(model.input_cost_per_token)}
                                  </TableCell>
                                  <TableCell>
                                    {formatPrice(model.output_cost_per_token)}
                                  </TableCell>
                                  {admin && (
                                    <TableCell>
                                      <Button
                                        variant="outline"
                                        size="sm"
                                        aria-label={`Remove ${model.model} from ${provider.name}`}
                                        onClick={() =>
                                          handleRemoveModel(
                                            provider.id,
                                            model.id
                                          )
                                        }
                                      >
                                        Remove
                                      </Button>
                                    </TableCell>
                                  )}
                                </TableRow>
                              ))}
                            </TableBody>
                          </Table>
                        )}
                      </TableCell>
                    </TableRow>
                  )}
                </Fragment>
              ))}
            </TableBody>
          </Table>
        )}
      </div>

      {admin && (
        <AddProviderDialog
          open={addOpen}
          onOpenChange={setAddOpen}
          onCreated={(provider) => {
            setProviders((prev) => [...prev, provider]);
            setAddOpen(false);
          }}
        />
      )}
    </div>
  );
}
