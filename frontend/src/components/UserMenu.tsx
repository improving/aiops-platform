"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { signOut, useSession } from "next-auth/react";
import { clearChatHistory } from "@/lib/chatStorage";
import { DEV_USER_COOKIE, readCookie, setOrgCookie } from "@/lib/orgCookie";
import { useOrg } from "@/hooks/useOrg";
import { orgService } from "@/services/orgService";
import type { OrganizationMembership } from "@/types/organization";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
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

/**
 * The organization block of the user menu (spec 5.5): the active
 * organization, a "Switch organization" submenu with every membership and
 * its role, and the links to the organization, token and audit pages.
 * Rendered in both auth modes; it reads the API, never the session.
 */
export function OrganizationMenuItems() {
  const { org, isAdmin } = useOrg();
  const [memberships, setMemberships] = useState<OrganizationMembership[]>([]);

  const fetchMemberships = useCallback(async () => {
    try {
      setMemberships((await orgService.getMine()).organizations);
    } catch {
      // The current organization still renders through useOrg(); a failed
      // membership list only leaves the switcher submenu empty.
    }
  }, []);

  useEffect(() => {
    (async () => {
      await fetchMemberships();
    })();
  }, [fetchMemberships]);

  if (!org) return null;

  const switchTo = (slug: string) => {
    if (slug === org.slug) return;
    setOrgCookie(slug);
    window.location.reload();
  };

  return (
    <>
      <DropdownMenuSeparator />
      <DropdownMenuLabel className="font-normal">
        <p className="text-xs text-muted-foreground">Organization</p>
        <p className="text-sm font-medium" data-testid="active-organization">
          {org.name}
        </p>
      </DropdownMenuLabel>
      <DropdownMenuSub>
        <DropdownMenuSubTrigger>Switch organization</DropdownMenuSubTrigger>
        <DropdownMenuSubContent>
          <DropdownMenuRadioGroup value={org.slug} onValueChange={switchTo}>
            {memberships.map((membership) => (
              <DropdownMenuRadioItem
                key={membership.slug}
                value={membership.slug}
              >
                {membership.name} · {membership.role}
              </DropdownMenuRadioItem>
            ))}
          </DropdownMenuRadioGroup>
        </DropdownMenuSubContent>
      </DropdownMenuSub>
      {isAdmin && (
        <DropdownMenuItem asChild>
          <Link href="/organization" prefetch={false}>
            Manage organization
          </Link>
        </DropdownMenuItem>
      )}
      <DropdownMenuItem asChild>
        <Link href="/settings/tokens" prefetch={false}>
          API tokens
        </Link>
      </DropdownMenuItem>
      {isAdmin && (
        <DropdownMenuItem asChild>
          <Link href="/audit" prefetch={false}>
            Audit log
          </Link>
        </DropdownMenuItem>
      )}
    </>
  );
}

// Avatar with a menu: name, email, the organization block and "Sign out".
// Rendered only in oidc mode (see Header.tsx), so useSession has a provider.
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
    clearChatHistory();
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
      <DropdownMenuContent align="end" className="w-64">
        <DropdownMenuLabel className="font-normal">
          <div className="flex flex-col space-y-1">
            <p className="text-sm font-medium leading-none">{name}</p>
            <p className="text-xs leading-none text-muted-foreground">
              {email}
            </p>
          </div>
        </DropdownMenuLabel>
        <OrganizationMenuItems />
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={onSignOut}>Sign out</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

// AUTH_MODE=disabled: no session, no sign-out, but the same organization
// block for the dev identity (the `aiops_dev_user` cookie names it).
export function DevUserMenu() {
  const [devUser, setDevUser] = useState("dev");

  useEffect(() => {
    (async () => {
      setDevUser(readCookie(DEV_USER_COOKIE) ?? "dev");
    })();
  }, []);

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
            <AvatarFallback>{initials(devUser)}</AvatarFallback>
          </Avatar>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-64">
        <DropdownMenuLabel className="font-normal">
          <div className="flex flex-col space-y-1">
            <p className="text-sm font-medium leading-none">{devUser}</p>
            <p className="text-xs leading-none text-muted-foreground">
              AUTH_MODE=disabled
            </p>
          </div>
        </DropdownMenuLabel>
        <OrganizationMenuItems />
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
