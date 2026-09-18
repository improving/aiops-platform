"use client";

import { type ReactNode, useState } from "react";
import { ChevronDownIcon } from "@radix-ui/react-icons";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { cn } from "@/lib/utils";

export interface ComboboxItem {
  /** What the search matches, and the React key. */
  value: string;
  /** More search terms (a label, a display name). */
  keywords?: string[];
  /** What the option shows; the value when omitted. */
  node?: ReactNode;
  /** The heading this option sits under; options without one come
      first, under no heading. Groups keep the order of first mention. */
  group?: string;
  /** Listed, but not selectable (a target that is still starting). */
  disabled?: boolean;
  onSelect: () => void;
}

function grouped(items: ComboboxItem[]): [string, ComboboxItem[]][] {
  const groups = new Map<string, ComboboxItem[]>();
  for (const item of items) {
    const key = item.group ?? "";
    groups.set(key, [...(groups.get(key) ?? []), item]);
  }
  return [...groups.entries()].sort(
    ([a], [b]) => Number(a !== "") - Number(b !== "")
  );
}

/**
 * A searchable dropdown: a trigger button (`role="combobox"`,
 * `aria-expanded`) opening a Popover with a Command list that closes on
 * select. The one place Popover and Command meet, so every picker has
 * the same accessibility contract and look.
 */
export function Combobox({
  label,
  ariaLabel,
  items,
  placeholder,
  emptyText = "No match.",
  disabled,
  variant = "outline",
  className,
  contentClassName,
  footer,
}: {
  /** The trigger's visible content. */
  label: ReactNode;
  /** The trigger's accessible name; a combobox does not name from its
      content, so a `getByRole("combobox", { name })` locator needs this. */
  ariaLabel?: string;
  items: ComboboxItem[];
  placeholder: string;
  emptyText?: ReactNode;
  disabled?: boolean;
  variant?: "outline" | "ghost";
  /** Trigger classes; the default width is 200px. */
  className?: string;
  /** Popover classes; the default width is 200px. */
  contentClassName?: string;
  /** Rendered under the list, inside the popover. */
  footer?: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant={variant}
          role="combobox"
          aria-label={ariaLabel}
          aria-expanded={open}
          disabled={disabled}
          className={cn("w-[200px] justify-between", className)}
        >
          {label}
          <ChevronDownIcon className="ml-2 h-4 w-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        className={cn("w-[200px] p-0", contentClassName)}
      >
        <Command>
          <CommandInput placeholder={placeholder} className="h-9" />
          <CommandList className="max-h-72">
            <CommandEmpty>{emptyText}</CommandEmpty>
            {grouped(items).map(([heading, members]) => (
              <CommandGroup key={heading} heading={heading || undefined}>
                {members.map((item) => (
                  <CommandItem
                    key={item.value}
                    value={item.value}
                    keywords={item.keywords}
                    disabled={item.disabled}
                    onSelect={() => {
                      item.onSelect();
                      setOpen(false);
                    }}
                  >
                    {item.node ?? item.value}
                  </CommandItem>
                ))}
              </CommandGroup>
            ))}
          </CommandList>
          {footer}
        </Command>
      </PopoverContent>
    </Popover>
  );
}
