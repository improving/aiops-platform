"use client";

import { signOut, useSession } from "next-auth/react";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Skeleton } from "@/components/ui/skeleton";

export function initials(name: string | null | undefined): string {
  const parts = (name ?? "").trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  return parts
    .slice(0, 2)
    .map((part) => part[0]!.toUpperCase())
    .join("");
}

// Avatar with a menu: name, email and "Sign out". Rendered only when the
// UI runs in oidc mode (see Header.tsx), so useSession always has a provider.
export function UserMenu() {
  const { data: session, status } = useSession();

  if (status === "loading") {
    return <Skeleton className="h-10 w-10 rounded-full" />;
  }
  if (!session?.user) {
    return (
      <Button asChild variant="outline" size="sm">
        <a href="/login">Sign in</a>
      </Button>
    );
  }

  const { name, email } = session.user;

  const onSignOut = async () => {
    // Drop the Auth.js cookie first, then end the Keycloak SSO session;
    // Keycloak sends the browser back to /login.
    await signOut({ redirect: false });
    window.location.assign(session.endSessionUrl ?? "/login");
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="rounded-full"
          aria-label="User menu"
        >
          <Avatar>
            <AvatarFallback>{initials(name)}</AvatarFallback>
          </Avatar>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        <DropdownMenuLabel className="font-normal">
          <div className="flex flex-col space-y-1">
            <p className="text-sm font-medium leading-none">{name}</p>
            <p className="text-xs leading-none text-muted-foreground">
              {email}
            </p>
          </div>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={onSignOut}>Sign out</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
