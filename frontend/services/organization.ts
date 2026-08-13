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

  async inviteUser(email: string, roleId: number): Promise<any> {
    const res = await api.post("/organizations/invitations", { email, role_id: roleId });
    return res.data;
  },

  async inviteBulkUsers(emails: string[], roleId: number): Promise<any[]> {
    const res = await api.post("/organizations/invitations/bulk", { emails, role_id: roleId });
    return res.data;
  },

  async acceptInvitation(token: string): Promise<any> {
    const res = await api.post("/organizations/invitations/accept", { token });
    return res.data;
  },
};
