import { api } from "@/utils/api";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: string;
  sources?: ChatSource[];
}

export interface ChatSession {
  id: string;
  title: string;
  createdAt: string;
}

export interface ChatSource {
  score: number;
  chunk_uuid: string;
  parsed_document_id: number;
  filename?: string; // Optional field if we map document name client-side
}

export interface SendMessageResponse {
  answer: string;
  sources: ChatSource[];
}

export const ChatService = {
  async sendMessage(question: string, knowledgeBaseId: number): Promise<SendMessageResponse> {
    const res = await api.post("/chat/", {
      question,
      knowledge_base_id: knowledgeBaseId
    });
    return res.data;
  },

  async getMessages(sessionId: string): Promise<ChatMessage[]> {
    return []; // Out of scope for Sprint 9
  },

  async getSessions(): Promise<ChatSession[]> {
    return []; // Out of scope for Sprint 9
  },
};
