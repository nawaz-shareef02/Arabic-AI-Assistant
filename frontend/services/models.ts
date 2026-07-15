export interface ModelConfig {
  id: string;
  name: string;
  provider: string;
  status: "Running" | "Offline" | "Checking" | "Waiting";
  available: boolean;
  latency: string;
  memory: string;
  health: string;
  version: string;
  description: string;
}

export const ModelsService = {
  async getModels(): Promise<ModelConfig[]> {
    return [
      {
        id: "deepseek-r1",
        name: "DeepSeek-R1",
        provider: "Ollama (Local Node)",
        status: "Waiting",
        available: false,
        latency: "—",
        memory: "—",
        health: "—",
        version: "—",
        description: "Reasoning model running locally via Ollama. Waiting for backend connection."
      },
      {
        id: "allam",
        name: "ALLaM",
        provider: "SDAIA Cloud",
        status: "Checking",
        available: false,
        latency: "—",
        memory: "—",
        health: "—",
        version: "—",
        description: "Bilingual model from Saudi Data & AI Authority. Currently offline."
      }
    ];
  }
};
