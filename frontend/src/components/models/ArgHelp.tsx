"use client";

import { InfoCircledIcon } from "@radix-ui/react-icons";

import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { type ArgKind, lookupArgDoc } from "@/lib/engineArgs";

/**
 * The info button of a CLI argument or environment variable row: what it
 * does, the engine's default, the range, and what to watch for on this
 * platform (lib/engineArgs.ts). Renders nothing for a name the catalog
 * does not know, so such a row has no button. A popover, not a
 * tooltip: it opens on a click next to a read-only input, where hover is
 * unreliable, and needs no provider. `type="button"`: the rows sit in the
 * launch form, and a bare button would submit it.
 */
export function ArgHelp({
  engineName,
  kind,
  name,
}: {
  engineName?: string;
  kind: ArgKind;
  name: string;
}) {
  const doc = lookupArgDoc(engineName, kind, name);
  if (!doc) return null;
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={`About ${doc.name}`}
          className="shrink-0 self-center rounded-full p-1 text-muted-foreground hover:text-foreground focus-visible:outline-2"
        >
          <InfoCircledIcon className="h-4 w-4" />
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80 space-y-2 text-sm">
        <p className="font-mono text-xs font-semibold">{doc.name}</p>
        <p>{doc.summary}</p>
        {doc.defaultValue && (
          <p>
            <span className="font-medium">Default:</span> {doc.defaultValue}
          </p>
        )}
        {doc.range && (
          <p>
            <span className="font-medium">Range:</span> {doc.range}
          </p>
        )}
        {doc.note && <p className="text-muted-foreground">{doc.note}</p>}
        {doc.docUrl && (
          <a
            href={doc.docUrl}
            target="_blank"
            rel="noreferrer"
            className="text-primary underline"
          >
            Documentation
          </a>
        )}
      </PopoverContent>
    </Popover>
  );
}
