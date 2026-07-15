import { api } from "@/utils/api";

export interface HealthStatus {
  apiServer: "online" | "offline" | "waiting";
  ollama: "online" | "offline" | "waiting";
  qdrant: "online" | "offline" | "waiting";
  postgres: "online" | "offline" | "waiting";
  redis: "online" | "offline" | "waiting";
}

export const HealthService = {
  async checkHealth(): Promise<HealthStatus> {
    try {
      // Endpoint is /health (FastAPI has prefix but this route is at root level? Let's check api.ts base URL)
      // api.ts base URL is http://localhost:8000/api/v1. So api.get("/health") calls http://localhost:8000/api/v1/health.
      // Wait, in backend/app/api/v1/health.py, the prefix is /health.
      // So the endpoint is /api/v1/health. Thus, api.get("/health") is correct!
      const res = await api.get("/health");
      const data = res.data;
      return {
        apiServer: data.apiServer || "offline",
        ollama: data.ollama || "offline",
        qdrant: data.qdrant || "offline",
        postgres: data.postgres || "offline",
        redis: data.redis || "offline"
      };
    } catch (e) {
      return {
        apiServer: "offline",
        ollama: "offline",
        qdrant: "offline",
        postgres: "offline",
        redis: "offline"
      };
    }
  },
};
