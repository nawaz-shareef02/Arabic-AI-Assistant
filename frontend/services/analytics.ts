import { api } from "@/utils/api";

export interface AnalyticsData {
  dailyQuestions: { date: string; count: number }[];
  storageGrowthMb: { date: string; count: number }[];
  latencyHistoryMs: { date: string; value: number }[];
  total_queries?: number;
  average_latency_ms?: number;
  top_queries?: { query: string; count: number }[];
  category_distribution?: { category: string; count: number }[];
  top_entities?: { text: string; type: string; count: number }[];
  unused_documents?: { uuid: string; filename: string; created_at: string; classification: string }[];
}

export interface HealthReport {
  score: number;
  status: string;
  total_documents: number;
  dimensions: Record<string, number>;
  issues: { type: string; severity: string; message: string }[];
}

export const AnalyticsService = {
  async getAnalytics(): Promise<AnalyticsData> {
    try {
      const res = await api.get("/analytics/summary");
      return res.data;
    } catch (e) {
      console.error("Error loading analytics data", e);
      return {
        dailyQuestions: [],
        storageGrowthMb: [],
        latencyHistoryMs: [],
      };
    }
  },

  async getHealth(kbUuid?: string): Promise<HealthReport> {
    try {
      const res = await api.get("/analytics/health");
      return res.data;
    } catch (e) {
      console.error("Error loading health report", e);
      return {
        score: 100,
        status: "Healthy",
        total_documents: 0,
        dimensions: {},
        issues: [],
      };
    }
  },
};
