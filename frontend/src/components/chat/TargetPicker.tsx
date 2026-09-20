import { Combobox, type ComboboxItem } from "@/components/ui/combobox";
import type { ChatTarget } from "@/types/models";

/**
 * The target as a searchable list: an organization with a hosted provider
 * has tens of models, which a plain select turns into a long scroll.
 * A deployed instance that is not ready yet is listed, not hidden, so
 * "where is my model" has an answer; it cannot be picked.
 */
export function TargetPicker({
  targets,
  selected,
  onSelect,
  className,
}: {
  /** Every chat-capable target, ready or not. */
  targets: ChatTarget[];
  /** May be one that is not ready: the trigger then says so. */
  selected?: ChatTarget;
  onSelect: (name: string) => void;
  /** The trigger's classes; by default it fills its container. */
  className?: string;
}) {
  const items: ComboboxItem[] = targets.map((t) => ({
    value: t.name,
    keywords: [t.label, t.model, t.engine],
    group: t.provider_id ? "Hosted" : "Deployed",
    disabled: !t.ready,
    node: (
      <span className="flex min-w-0 flex-1 items-center justify-between gap-2">
        <span className="truncate">{t.label}</span>
        {!t.ready && (
          <span className="shrink-0 text-xs text-muted-foreground">
            Starting
          </span>
        )}
      </span>
    ),
    onSelect: () => onSelect(t.name),
  }));
  return (
    <Combobox
      ariaLabel="Target"
      label={
        <span className="min-w-0 truncate font-normal">
          {selected ? (
            `${selected.label}${selected.ready ? "" : " · Starting"}`
          ) : (
            <span className="text-muted-foreground">Pick an instance</span>
          )}
        </span>
      }
      items={items}
      placeholder="Search targets"
      emptyText="No target matches."
      className={className ?? "w-full min-w-0"}
      contentClassName="w-[min(28rem,calc(100vw-2rem))]"
    />
  );
}
