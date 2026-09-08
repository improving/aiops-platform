"use client";

import { useState } from "react";
import {
  ClipboardCopyIcon,
  EyeClosedIcon,
  EyeOpenIcon,
} from "@radix-ui/react-icons";
import { Button } from "@/components/ui/button";
import { useCopy } from "@/components/CopyButton";

// A fixed-width mask, so neither the value nor its length shows on screen.
const MASK = "•".repeat(16);

/**
 * A secret shown masked by default, so it never lands in a screen
 * recording or a shared screen unasked. Copy always copies the real
 * value to the clipboard without revealing it; the eye toggles the
 * value on screen for the reader who does want to see it.
 *
 * The value still lives in the DOM (masked is a display choice, not
 * storage), so keep the caller's "shown once, not stored by the UI"
 * guarantee: the value is only ever in memory while its dialog is open.
 */
export function MaskedSecret({
  value,
  label,
  testId,
}: {
  value: string;
  /** Names the value for the reader and the copy/reveal controls. */
  label: string;
  testId?: string;
}) {
  const [shown, setShown] = useState(false);
  const copy = useCopy();
  return (
    <div className="flex items-center gap-2">
      <code
        aria-label={label}
        data-testid={testId}
        className="flex-1 select-none rounded bg-muted px-2 py-1 font-mono text-xs break-all"
      >
        {shown ? value : MASK}
      </code>
      <Button
        type="button"
        variant="outline"
        size="sm"
        aria-label={shown ? `Hide ${label}` : `Reveal ${label}`}
        aria-pressed={shown}
        onClick={() => setShown((s) => !s)}
        icon={
          shown ? (
            <EyeClosedIcon className="h-4 w-4" />
          ) : (
            <EyeOpenIcon className="h-4 w-4" />
          )
        }
      />
      <Button
        type="button"
        variant="outline"
        size="sm"
        aria-label={`Copy ${label}`}
        onClick={() => copy(value, label)}
        icon={<ClipboardCopyIcon className="h-4 w-4" />}
      />
    </div>
  );
}
