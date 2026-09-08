"use client";

import { Button } from "@/components/ui/button";
import { useToast } from "@/components/hooks/use-toast";
import { ClipboardCopyIcon } from "@radix-ui/react-icons";

/**
 * The one clipboard write in the UI: `copy(text, label)` copies and
 * confirms with a toast ("<label> copied to clipboard"), or explains the
 * failure. CopyButton wraps it; a control that copies on select (a
 * picker's option) calls it directly.
 */
export function useCopy() {
  const { toast } = useToast();
  return async (text: string, label: string) => {
    try {
      await navigator.clipboard.writeText(text);
      toast({ title: "Copied", description: `${label} copied to clipboard` });
    } catch {
      toast({
        title: "Copy failed",
        description: "Select the text and copy it manually",
        variant: "destructive",
      });
    }
  };
}

/** Copies `text` and confirms with a toast; aria-label is "Copy <label>". */
export function CopyButton({
  label,
  text,
  size = "sm",
}: {
  label: string;
  text: string;
  size?: "sm" | "default";
}) {
  const copy = useCopy();
  return (
    <Button
      type="button"
      variant="outline"
      size={size}
      aria-label={`Copy ${label}`}
      onClick={() => copy(text, label)}
      icon={<ClipboardCopyIcon className="w-4 h-4" />}
    />
  );
}
