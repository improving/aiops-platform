import { Label } from "@/components/ui/label";

/**
 * A label/value row in a detail page's `grid grid-cols-2` layout, shared by
 * the inference, notebook and vector database instance detail pages.
 * `e2e/pages/notebooks.ts` `field()` locates the value with
 * `following-sibling::span[1]` off the label's exact text, so the value is
 * always wrapped in one `<span>`. `valueClassName` is opt-in and defaults to
 * none: most rows on the inference and notebook pages were a bare
 * `<span>{value}</span>` before this component existed, and only the vector
 * database page's rows wrapped the value in `flex items-center gap-2
 * break-all` -- pass that string explicitly to reproduce it, rather than
 * applying it (and its `break-all`) to every row by default.
 */
export function DetailRow({
  label,
  valueClassName,
  children,
}: {
  label: string;
  valueClassName?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="grid grid-cols-2 items-center gap-4">
      <Label>{label}</Label>
      <span className={valueClassName}>{children}</span>
    </div>
  );
}
