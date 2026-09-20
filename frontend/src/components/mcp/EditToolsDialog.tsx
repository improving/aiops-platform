"use client";

import { useEffect, useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/hooks/use-toast";
import { parseApiError } from "@/lib/utils";
import { mcpService } from "@/services/mcpService";
import type { McpApproval, McpServer } from "@/types/mcp";
import { ApprovalField } from "@/components/mcp/ApprovalField";
import { ToolPicker } from "@/components/mcp/ToolPicker";

/** "Edit tools" (W4/W5): the same allow-all-or-selected picker as the add
    flow's step 2, seeded from the server's current setting. */
export function EditToolsDialog({
  server,
  open,
  onOpenChange,
  onUpdated,
}: {
  server: McpServer | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onUpdated: (server: McpServer) => void;
}) {
  const { toast } = useToast();
  const [allowAll, setAllowAll] = useState(true);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [approval, setApproval] = useState<McpApproval>("never");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open && server) {
      setApproval(server.approval ?? "never");
      setAllowAll(server.allowed_tools === null);
      setSelected(
        new Set(server.allowed_tools ?? server.tools.map((t) => t.name))
      );
    }
  }, [open, server]);

  const toggleTool = (name: string, checked: boolean) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (checked) next.add(name);
      else next.delete(name);
      return next;
    });
  };

  const handleSave = async () => {
    if (!server) return;
    setSaving(true);
    try {
      const updated = await mcpService.updateServer(
        server.id,
        allowAll
          ? { allow_all_tools: true, approval }
          : { allowed_tools: Array.from(selected), approval }
      );
      toast({
        title: "Success",
        description: "Tools updated",
        variant: "success",
      });
      onUpdated(updated);
      onOpenChange(false);
    } catch (err) {
      toast(parseApiError(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Edit tools</DialogTitle>
          <DialogDescription>
            {server ? `Which tools ${server.name} may call.` : ""}
          </DialogDescription>
        </DialogHeader>
        {server && (
          <ToolPicker
            idPrefix="mcp-edit"
            tools={server.tools}
            allowAll={allowAll}
            onAllowAllChange={setAllowAll}
            selected={selected}
            onToggle={toggleTool}
          />
        )}
        {server && (
          <ApprovalField
            idPrefix="mcp-edit"
            value={approval}
            onChange={setApproval}
          />
        )}
        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={saving}
          >
            Cancel
          </Button>
          <Button type="button" onClick={handleSave} loading={saving}>
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
