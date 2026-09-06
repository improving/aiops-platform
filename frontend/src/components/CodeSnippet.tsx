import { CopyButton } from "@/components/CopyButton";

/** A code block with its own copy button; `label` names it for assistive tech. */
export function CodeSnippet({ label, code }: { label: string; code: string }) {
  return (
    <div className="relative">
      <pre
        role="group"
        aria-label={label}
        className="overflow-x-auto rounded-md bg-muted p-3 pr-12 text-xs"
      >
        {code}
      </pre>
      <div className="absolute right-2 top-2">
        <CopyButton label={label} text={code} />
      </div>
    </div>
  );
}
