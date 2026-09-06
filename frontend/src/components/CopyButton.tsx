"use client";

import { Button } from "@/components/ui/button";
import { useToast } from "@/components/hooks/use-toast";
import { ClipboardCopyIcon } from "@radix-ui/react-icons";

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
  const { toast } = useToast();
  const copy = async () => {
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
  return (
    <Button
      type="button"
      variant="outline"
      size={size}
      aria-label={`Copy ${label}`}
      onClick={copy}
      icon={<ClipboardCopyIcon className="w-4 h-4" />}
    />
  );
}
