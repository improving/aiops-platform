"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { SettingRows } from "@/components/models/SettingRows";
import { ToolCallingSwitch } from "@/components/models/ToolCallingSwitch";
import { useToast } from "@/components/hooks/use-toast";
import {
  duplicateName,
  ownValues,
  rowsFromDefaults,
  type SettingRow,
} from "@/lib/instanceSettings";
import { parseApiError } from "@/lib/utils";
import { modelService, upstreamModel } from "@/services/modelService";
import type { InferenceInstance } from "@/types/models";

/**
 * The CLI arguments and environment variables of a deployed instance.
 *
 * The rows are the engine's defaults overlaid with the instance's own
 * values, as the launch wizard showed them; Save sends the own values
 * only, and the backend upgrades the release, so the pods restart.
 * Only what the engine's controller reads is shown (the payload's
 * `settingsRead`).
 *
 * The form mounts with the dialog, so every opening starts from the
 * instance as it is now, not from an abandoned edit.
 */
export function EditSettingsDialog({
  instance,
  open,
  onOpenChange,
  onSaved,
}: {
  instance: InferenceInstance;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved: () => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
        {open && (
          <SettingsForm
            instance={instance}
            onClose={() => onOpenChange(false)}
            onSaved={onSaved}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}

function SettingsForm({
  instance,
  onClose,
  onSaved,
}: {
  instance: InferenceInstance;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { toast } = useToast();
  const category = instance.model.category;
  const settingsRead = instance.settingsRead ?? [];
  const read = {
    args: settingsRead.includes("args"),
    env: settingsRead.includes("env_vars"),
  };
  const ofCategory = <T extends { chart_type: string }>(defaults: T[]) =>
    defaults.filter((d) => d.chart_type === category);
  const [args, setArgs] = useState<SettingRow[]>(() =>
    rowsFromDefaults(
      ofCategory(instance.engine.default_args),
      instance.config?.args
    )
  );
  const [envVars, setEnvVars] = useState<SettingRow[]>(() =>
    rowsFromDefaults(
      ofCategory(instance.engine.default_config),
      instance.config?.env_vars
    )
  );
  const [saving, setSaving] = useState(false);
  const stopped = instance.status === "Stopped";
  const unnamed = [...args, ...envVars].some((row) => row.name.trim() === "");
  const repeated = duplicateName(args) ?? duplicateName(envVars);

  const save = async (event: React.FormEvent) => {
    event.preventDefault();
    setSaving(true);
    try {
      await modelService.updateInferenceInstanceSettings(instance.id, {
        args: read.args ? ownValues(args) : {},
        env_vars: read.env ? ownValues(envVars) : {},
      });
      toast({
        title: "Settings saved",
        description: stopped
          ? "They apply when the instance is resumed."
          : "The instance restarts with them.",
      });
      onClose();
      onSaved();
    } catch (error) {
      toast(parseApiError(error));
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={save} className="min-w-0 space-y-4">
      <DialogHeader>
        <DialogTitle>Edit settings</DialogTitle>
        <DialogDescription>
          {stopped
            ? "The instance is stopped: the settings are stored and apply when it is resumed."
            : "Saving restarts the instance with the new settings. It cannot answer until it is ready again; a model that is already downloaded starts from the cache."}
        </DialogDescription>
      </DialogHeader>
      {read.args && (
        <section aria-label="CLI arguments">
          <h3 className="mb-3 font-semibold">CLI arguments</h3>
          {instance.engine.name === "vLLM" && (
            <ToolCallingSwitch
              rows={args}
              onChange={setArgs}
              modelReference={upstreamModel(instance)}
            />
          )}
          <SettingRows
            kind="arg"
            rows={args}
            onChange={setArgs}
            engineName={instance.engine.name}
          />
        </section>
      )}
      {read.env && (
        <section aria-label="Environment variables">
          <h3 className="mb-3 font-semibold">Environment variables</h3>
          <SettingRows
            kind="env"
            rows={envVars}
            onChange={setEnvVars}
            engineName={instance.engine.name}
          />
        </section>
      )}
      {repeated && (
        <p role="alert" className="text-sm text-destructive">
          {repeated} is there twice. Keep one row for it.
        </p>
      )}
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onClose}>
          Cancel
        </Button>
        <Button
          type="submit"
          loading={saving}
          disabled={saving || unnamed || !!repeated}
        >
          {stopped ? "Save" : "Save and restart"}
        </Button>
      </DialogFooter>
    </form>
  );
}
