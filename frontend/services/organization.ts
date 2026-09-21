import { api } from "@/utils/api";

export interface OrganizationMemberItem {
  id: number;
  user_id: number;
  user_uuid: string;
  full_name: string;
  email: string;
  roles: string[];
  joined_at: string;
}

export interface ActivityFeedItem {
  id: number;
  uuid: string;
  timestamp: string;
  user_id?: number;
  user_email: string;
  category: string;
  action: string;
  resource_type: string;
  status: string;
}

export interface OrganizationInvitationItem {
  id: number;
  uuid: string;
  email: string;
  role_id: number;
  role_name: string;
  status: string;
  expires_at: string;
  accepted_at?: string;
  created_at: string;
}

export interface VerifyInvitationResponse {
  valid: boolean;
  reason?: string;
  detail?: string;
  email?: string;
  organization_name?: string;
  role_name?: string;
  expires_at?: string;
  user_exists?: boolean;
}

export interface AcceptInvitationPayload {
  token: string;
  full_name?: string;
  password?: string;
}

export const OrganizationService = {
  async getMembers(orgId: number): Promise<OrganizationMemberItem[]> {
    try {
      const res = await api.get(`/organizations/${orgId}/members`);
      return res.data;
    } catch (e) {
      console.error("Error fetching organization members", e);
      return [];
    }
  },

  async getActivityFeed(orgId: number, limit = 50): Promise<ActivityFeedItem[]> {
    try {
      const res = await api.get(`/organizations/${orgId}/activity`, { params: { limit } });
      return res.data;
    } catch (e) {
      console.error("Error fetching organization activity feed", e);
      return [];
    }
  },

  async getInvitations(status?: string): Promise<OrganizationInvitationItem[]> {
    try {
      const res = await api.get("/organizations/invitations", {
        params: status ? { status } : {},
      });
      return res.data;
    } catch (e) {
      console.error("Error fetching invitations", e);
      return [];
    }
  },

  async inviteUser(email: string, roleId: number): Promise<any> {
    const res = await api.post("/organizations/invitations", { email, role_id: roleId });
    return res.data;
  },

  async inviteBulkUsers(emails: string[], roleId: number): Promise<any[]> {
    const res = await api.post("/organizations/invitations/bulk", { emails, role_id: roleId });
    return res.data;
  },

  async verifyInvitation(token: string): Promise<VerifyInvitationResponse> {
    const res = await api.get("/organizations/invitations/verify", {
      params: { token },
    });
    return res.data;
  },

  async acceptInvitation(payload: AcceptInvitationPayload): Promise<any> {
    const res = await api.post("/organizations/invitations/accept", payload);
    return res.data;
  },

  async cancelInvitation(uuid: string): Promise<any> {
    const res = await api.post(`/organizations/invitations/${uuid}/cancel`);
    return res.data;
  },

  async resendInvitation(uuid: string): Promise<any> {
    const res = await api.post(`/organizations/invitations/${uuid}/resend`);
    return res.data;
  },
};
