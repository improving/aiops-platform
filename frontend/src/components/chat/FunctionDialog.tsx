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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  EXAMPLE_PARAMETERS,
  functionProblem,
  type PlaygroundFunction,
} from "@/components/chat/usePlaygroundFunctions";

/**
 * Define or edit one function for the playground. Mounted with a `key`
 * per opening, so its fields start from `initial` without an effect.
 */
export function FunctionDialog({
  initial,
  otherNames,
  onOpenChange,
  onSave,
  onDelete,
}: {
  /** null: a new function. */
  initial: PlaygroundFunction | null;
  otherNames: string[];
  onOpenChange: (open: boolean) => void;
  onSave: (fn: PlaygroundFunction, previousName?: string) => void;
  onDelete?: (name: string) => void;
}) {
  const [name, setName] = useState(initial?.name ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [parameters, setParameters] = useState(
    initial?.parameters ?? EXAMPLE_PARAMETERS
  );
  const problem = name ? functionProblem({ name, parameters }, otherNames) : "";

  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {initial ? "Edit function" : "Add function"}
          </DialogTitle>
          <DialogDescription>
            The model may call it. Nothing runs: you type the result, and the
            model goes on from there.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div className="space-y-1">
            <Label htmlFor="fn-name">Function name</Label>
            <Input
              id="fn-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="get_weather"
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="fn-description">What it does</Label>
            <Input
              id="fn-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="The weather in a city, now"
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="fn-parameters">Parameters (JSON Schema)</Label>
            <Textarea
              id="fn-parameters"
              className="font-mono text-xs"
              rows={9}
              value={parameters}
              onChange={(e) => setParameters(e.target.value)}
            />
          </div>
          {problem && (
            <p role="alert" className="text-sm text-destructive">
              {problem}
            </p>
          )}
        </div>
        <DialogFooter>
          {initial && onDelete && (
            <Button
              type="button"
              variant="outline"
              className="mr-auto"
              onClick={() => {
                onDelete(initial.name);
                onOpenChange(false);
              }}
            >
              Delete function
            </Button>
          )}
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
          >
            Cancel
          </Button>
          <Button
            type="button"
            disabled={!name || problem !== ""}
            onClick={() => {
              onSave(
                {
                  name,
                  description: description.trim(),
                  parameters,
                  enabled: initial?.enabled ?? true,
                },
                initial?.name
              );
              onOpenChange(false);
            }}
          >
            Save function
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
