"use client";

import { useState } from "react";
import Link from "next/link";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { HamburgerMenuIcon } from "@radix-ui/react-icons";
import { cn } from "@/lib/utils";

interface MenuSubItem {
  label: string;
  href: string;
  description: string;
}

interface MenuItem {
  label: string;
  icon: React.ReactNode;
  href?: string;
  items?: MenuSubItem[];
}

interface MobileNavProps {
  menuItems: MenuItem[];
  isActive: (href: string) => boolean;
}

// Renders the same `menuItems` array as the desktop `NavigationMenu`, inside
// a shadcn `Sheet`, for viewports below the `md` breakpoint.
export function MobileNav({ menuItems, isActive }: MobileNavProps) {
  const [open, setOpen] = useState(false);

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        <Button variant="outline" size="icon" aria-label="Open menu">
          <HamburgerMenuIcon className="h-5 w-5" />
        </Button>
      </SheetTrigger>
      <SheetContent side="right" className="overflow-y-auto">
        <SheetHeader>
          <SheetTitle>Menu</SheetTitle>
        </SheetHeader>
        <nav className="flex flex-col gap-1 px-4 pb-4">
          {menuItems.map((item) =>
            item.items ? (
              <div key={item.label} className="flex flex-col gap-1">
                <div
                  className={cn(
                    "flex items-center px-2 py-2 text-sm font-medium text-muted-foreground",
                    item.items.some((subItem) => isActive(subItem.href)) &&
                      "font-bold text-primary"
                  )}
                >
                  {item.icon}
                  {item.label}
                </div>
                <div className="flex flex-col gap-1 pl-6">
                  {item.items.map((subItem) => (
                    <Link
                      key={subItem.href}
                      href={subItem.href}
                      onClick={() => setOpen(false)}
                      className={cn(
                        "rounded-md px-2 py-2 text-sm hover:bg-accent hover:text-accent-foreground",
                        isActive(subItem.href) &&
                          "bg-accent font-bold text-primary"
                      )}
                    >
                      {subItem.label}
                    </Link>
                  ))}
                </div>
              </div>
            ) : (
              <Link
                key={item.label}
                href={item.href as string}
                onClick={() => setOpen(false)}
                className={cn(
                  "flex items-center rounded-md px-2 py-2 text-sm font-medium hover:bg-accent hover:text-accent-foreground",
                  isActive(item.href as string) && "font-bold text-primary"
                )}
              >
                {item.icon}
                {item.label}
              </Link>
            )
          )}
        </nav>
      </SheetContent>
    </Sheet>
  );
}
