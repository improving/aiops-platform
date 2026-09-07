import api from "./api";
import type {
  CurrentOrganization,
  Invitation,
  MyOrganizations,
  OrgRole,
  OrganizationMember,
  OrganizationMembership,
} from "@/types/organization";

const BASE = "/api/v1alpha1/organizations";

export const orgService = {
  getMine: async () => {
    const response = await api.get<MyOrganizations>(BASE);
    return response.data;
  },
  getCurrent: async () => {
    const response = await api.get<CurrentOrganization>(`${BASE}/current`);
    return response.data;
  },
  create: async (body: { slug: string; name: string }) => {
    const response = await api.post<OrganizationMembership>(BASE, body);
    return response.data;
  },
  getMembers: async () => {
    const response = await api.get<OrganizationMember[]>(
      `${BASE}/current/members`
    );
    return response.data;
  },
  setMemberRole: async (userId: string, role: OrgRole) => {
    const response = await api.put<OrganizationMember>(
      `${BASE}/current/members/${userId}`,
      { role }
    );
    return response.data;
  },
  removeMember: async (userId: string) => {
    await api.delete(`${BASE}/current/members/${userId}`);
  },
  getInvitations: async () => {
    const response = await api.get<Invitation[]>(`${BASE}/current/invitations`);
    return response.data;
  },
  invite: async (body: { email: string; role: OrgRole }) => {
    const response = await api.post<Invitation>(
      `${BASE}/current/invitations`,
      body
    );
    return response.data;
  },
  withdrawInvitation: async (id: string) => {
    await api.delete(`${BASE}/current/invitations/${id}`);
  },
};
