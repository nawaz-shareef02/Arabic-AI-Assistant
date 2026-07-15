import { api } from "@/utils/api";

export interface RecentActivityItem {
  uuid: string;
  filename: string;
  mime_type: string;
  status: string;
  created_at: string;
  kb_name: string;
  kb_uuid: string;
}

export interface DashboardStats {
  documents: number;
  questions: number;
  knowledgeBases: number;
  storageUsedMb: number;
  recentActivity: RecentActivityItem[];
  uploadedDocs: number;
  parsingDocs: number;
  parsedDocs: number;
  failedDocs: number;
}

export const DashboardService = {
  async getStats(): Promise<DashboardStats> {
    try {
      const res = await api.get("/dashboard/summary");
      return {
        documents: res.data.documents,
        questions: 0, // Placeholder until chat QA is fully connected
        knowledgeBases: res.data.knowledge_bases,
        storageUsedMb: res.data.storage_used_mb,
        recentActivity: res.data.recent_activity || [],
        uploadedDocs: res.data.uploaded_docs || 0,
        parsingDocs: res.data.parsing_docs || 0,
        parsedDocs: res.data.parsed_docs || 0,
        failedDocs: res.data.failed_docs || 0,
      };
    } catch (e) {
      console.error("Error loading dashboard summary stats", e);
      return {
        documents: 0,
        questions: 0,
        knowledgeBases: 0,
        storageUsedMb: 0,
        recentActivity: [],
        uploadedDocs: 0,
        parsingDocs: 0,
        parsedDocs: 0,
        failedDocs: 0,
      };
    }
  },
};

