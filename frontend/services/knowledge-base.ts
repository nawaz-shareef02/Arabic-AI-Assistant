import { api } from "@/utils/api";

export interface KnowledgeBaseItem {
  id: number;
  uuid: string;
  name: string;
  docsCount: number;
  owner: string;
  storage: string;
  date: string;
}

export const KnowledgeBaseService = {
  async getKnowledgeBases(): Promise<KnowledgeBaseItem[]> {
    try {
      const res = await api.get("/knowledge-bases");
      return res.data.map((kb: any) => ({
        id: kb.id,
        uuid: kb.uuid,
        name: kb.name,
        docsCount: 0, // Placeholder count, to be populated dynamically
        owner: kb.created_by ? `User ${kb.created_by}` : "System",
        storage: "0 MB",
        date: new Date(kb.created_at).toLocaleDateString()
      }));
    } catch (e) {
      console.error("Error loading knowledge bases", e);
      return [];
    }
  },

  async createKnowledgeBase(name: string): Promise<KnowledgeBaseItem> {
    const res = await api.post("/knowledge-bases", {
      name,
      description: "Enterprise Knowledge Base Collection"
    });
    
    const kb = res.data;
    return {
      id: kb.id,
      uuid: kb.uuid,
      name: kb.name,
      docsCount: 0,
      owner: "Me",
      storage: "0 MB",
      date: new Date(kb.created_at).toLocaleDateString()
    };
  },

  async deleteKnowledgeBase(uuid: string): Promise<boolean> {
    await api.delete(`/knowledge-bases/${uuid}`);
    return true;
  },
};

