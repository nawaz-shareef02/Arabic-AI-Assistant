import { api } from "@/utils/api";

export interface AuditItem {
  id: number;
  uuid: string;
  timestamp: string;
  user_id?: number;
  user_email?: string;
  organization_id?: number;
  workspace_id?: number;
  category: string;
  action: string;
  resource_type: string;
  resource_id?: string;
  http_method?: string;
  api_endpoint?: string;
  client_ip?: string;
  request_id?: string;
  correlation_id?: string;
  status: string;
  metadata?: Record<string, any>;
}

export interface AuditSearchResponse {
  total: number;
  page: number;
  page_size: number;
  items: AuditItem[];
}

export const AuditService = {
  async getAuditLogs(params: {
    category?: string;
    action?: string;
    user_id?: number;
    status_filter?: string;
    page?: number;
    page_size?: number;
  } = {}): Promise<AuditSearchResponse> {
    try {
      const res = await api.get("/audit", { params });
      return res.data;
    } catch (e) {
      console.error("Error fetching audit logs", e);
      return { total: 0, page: 1, page_size: 50, items: [] };
    }
  },

  async exportAuditCsv(params: { category?: string; action?: string; user_id?: number } = {}): Promise<Blob> {
    const res = await api.get("/audit/export", {
      params,
      responseType: "blob",
    });
    return res.data;
  },
};
