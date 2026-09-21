import { api, getCsrfToken } from "@/utils/api";

// ─────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: string;
  sources?: ChatSource[];
}

export interface ChatSource {
  score: number;
  chunk_uuid: string;
  parsed_document_id: number;
  filename?: string;
}

export interface SendMessageResponse {
  answer: string;
  sources: ChatSource[];
}

// ─────────────────────────────────────────────
// Conversation Types (Sprint 11)
// ─────────────────────────────────────────────

export interface ConversationResponse {
  id: number;
  uuid: string;
  title: string | null;
  user_id: number;
  knowledge_base_id: number;
  status: "ACTIVE" | "ARCHIVED" | "DELETED";
  is_pinned: boolean;
  last_message_at: string | null;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface MessageResponse {
  id: number;
  conversation_id: number;
  role: "user" | "assistant" | "system";
  content: string;
  citations: ChatSource[] | null;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  created_at: string;
}

export interface ConversationWithMessages extends ConversationResponse {
  messages: MessageResponse[];
}

export interface ConversationListResponse {
  conversations: ConversationResponse[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface ConversationListParams {
  page?: number;
  page_size?: number;
  search?: string;
  status?: "ACTIVE" | "ARCHIVED" | "DELETED";
  knowledge_base_id?: number;
  sort_by?: "last_message_at" | "created_at" | "title";
}

// ─────────────────────────────────────────────
// Chat Service
// ─────────────────────────────────────────────

export const ChatService = {
  async sendMessage(
    question: string,
    knowledgeBaseId: number,
    conversationId?: number
  ): Promise<SendMessageResponse> {
    const res = await api.post("/chat/", {
      question,
      knowledge_base_id: knowledgeBaseId,
      ...(conversationId != null && { conversation_id: conversationId }),
    });
    return res.data;
  },

  async streamMessage(
    question: string,
    knowledgeBaseId: number,
    onChunk: (chunk: string) => void,
    signal?: AbortSignal,
    conversationId?: number
  ): Promise<void> {
    const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
    const csrfToken = getCsrfToken();
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      ...(csrfToken ? { "X-CSRF-Token": csrfToken } : {}),
    };

    const response = await fetch(`${API_URL}/api/v1/chat/stream`, {
      method: "POST",
      headers,
      credentials: "include", // Transmit HttpOnly auth_token & csrf_token cookies automatically
      body: JSON.stringify({
        question,
        knowledge_base_id: knowledgeBaseId,
        ...(conversationId != null && { conversation_id: conversationId }),
      }),
      signal,
    });

    if (!response.ok) {
      let errorMsg = `Streaming failed with status ${response.status}`;
      try {
        const errorJson = await response.json();
        if (errorJson.detail) {
          errorMsg =
            typeof errorJson.detail === "string"
              ? errorJson.detail
              : JSON.stringify(errorJson.detail);
        }
      } catch {
        // Ignored
      }
      throw new Error(errorMsg);
    }

    if (!response.body) {
      throw new Error("No response body received for streaming request.");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        if (value) {
          const text = decoder.decode(value, { stream: true });
          onChunk(text);
        }
      }
    } finally {
      reader.releaseLock();
    }
  },
};

// ─────────────────────────────────────────────
// Conversation Service (Sprint 11)
// ─────────────────────────────────────────────

export const ConversationService = {
  async create(
    knowledgeBaseId: number,
    title?: string
  ): Promise<ConversationResponse> {
    const res = await api.post("/conversations/", {
      knowledge_base_id: knowledgeBaseId,
      ...(title && { title }),
    });
    return res.data;
  },

  async list(params: ConversationListParams = {}): Promise<ConversationListResponse> {
    const res = await api.get("/conversations/", { params });
    return res.data;
  },

  async get(conversationId: number): Promise<ConversationWithMessages> {
    const res = await api.get(`/conversations/${conversationId}`);
    return res.data;
  },

  async update(
    conversationId: number,
    payload: { title?: string; status?: string; is_pinned?: boolean }
  ): Promise<ConversationResponse> {
    const res = await api.patch(`/conversations/${conversationId}`, payload);
    return res.data;
  },

  async delete(conversationId: number): Promise<void> {
    await api.delete(`/conversations/${conversationId}`);
  },

  async rename(conversationId: number, title: string): Promise<ConversationResponse> {
    return this.update(conversationId, { title });
  },

  async archive(conversationId: number): Promise<ConversationResponse> {
    return this.update(conversationId, { status: "ARCHIVED" });
  },

  async restore(conversationId: number): Promise<ConversationResponse> {
    return this.update(conversationId, { status: "ACTIVE" });
  },

  async pin(conversationId: number, pinned: boolean): Promise<ConversationResponse> {
    return this.update(conversationId, { is_pinned: pinned });
  },
};
