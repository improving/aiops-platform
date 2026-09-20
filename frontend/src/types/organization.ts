// Response shapes of the identity endpoints (backend/api/organizations.py,
// backend/api/audit.py, backend/api/tokens.py). Kept apart from
// types/models.ts, which the operations stream owns.

export type OrgRole = "admin" | "member" | "viewer";
export const ROLES: OrgRole[] = ["admin", "member", "viewer"];

export interface OrganizationMembership {
  id: string;
  slug: string;
  name: string;
  role: OrgRole;
}

// GET /v1alpha1/organizations
export interface MyOrganizations {
  organizations: OrganizationMembership[];
  active: string;
}

// GET /v1alpha1/organizations/current
export interface CurrentOrganization {
  id: string;
  slug: string;
  name: string;
  role: OrgRole;
  budget_usd: number | null;
  member_count: number;
  is_platform_admin: boolean;
}

// GET /v1alpha1/organizations/current/members
export interface OrganizationMember {
  user_id: string;
  email: string | null;
  name: string | null;
  role: OrgRole;
  created_at: string | null;
  last_seen_at: string | null;
}

// GET/POST /v1alpha1/organizations/current/invitations
export interface Invitation {
  id: string;
  email: string;
  role: OrgRole;
  invited_by: string | null;
  created_at: string;
  accepted_at: string | null;
  accepted_user_id: string | null;
}

// GET /v1alpha1/organizations/current/audit
export interface AuditEvent {
  id: string;
  at: string;
  actor_id: string | null;
  actor_label: string;
  action: string;
  resource_kind: string;
  resource_id: string | null;
  outcome: number;
  request_id: string | null;
  detail: Record<string, unknown> | null;
}

export interface AuditPage {
  events: AuditEvent[];
  next_cursor: string | null;
}

export interface AuditFilters {
  from?: string;
  to?: string;
  actor?: string;
  action?: string;
  resource_kind?: string;
  limit?: number;
  cursor?: string;
}

// GET/POST /v1alpha1/tokens
export interface ApiToken {
  id: string;
  name: string;
  prefix: string;
  scope: "read" | "write" | "mcp";
  created_at: string;
  expires_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
}

export interface CreatedApiToken extends ApiToken {
  /** The full token, shown once. */
  token: string;
}
