export interface AnalyticsData {
  dailyQuestions: { date: string; count: number }[];
  storageGrowthMb: { date: string; count: number }[];
  latencyHistoryMs: { date: string; value: number }[];
}

export const AnalyticsService = {
  async getAnalytics(): Promise<AnalyticsData> {
    return {
      dailyQuestions: [],
      storageGrowthMb: [],
      latencyHistoryMs: [],
    };
  },
};
