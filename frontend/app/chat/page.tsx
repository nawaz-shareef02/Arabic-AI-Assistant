"use client";

import React, { useState, useEffect, useRef, useCallback } from "react";
import {
  ChatService,
  ChatMessage,
  ChatSource,
  ConversationService,
  ConversationResponse,
  MessageResponse,
} from "@/services/chat";
import { useKnowledgeBase } from "@/context/KnowledgeBaseContext";
import { HealthService } from "@/services/health";
import { DocumentsService, DocumentItem } from "@/services/documents";
import {
  Send,
  Cpu,
  AlertTriangle,
  Bot,
  Terminal,
  Lock,
  Loader2,
  Square,
  Plus,
  MessageSquare,
  Archive,
  ArchiveRestore,
  Pin,
  PinOff,
  Trash2,
  Pencil,
  Check,
  X,
  Search,
  ChevronRight,
} from "lucide-react";
import { cn } from "@/lib/utils";
import Link from "next/link";

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────

function groupConversations(conversations: ConversationResponse[]) {
  const now = new Date();
  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterdayStart = new Date(todayStart);
  yesterdayStart.setDate(yesterdayStart.getDate() - 1);
  const weekStart = new Date(todayStart);
  weekStart.setDate(weekStart.getDate() - 7);

  const pinned: ConversationResponse[] = [];
  const today: ConversationResponse[] = [];
  const yesterday: ConversationResponse[] = [];
  const lastWeek: ConversationResponse[] = [];
  const older: ConversationResponse[] = [];
  const archived: ConversationResponse[] = [];

  for (const conv of conversations) {
    if (conv.status === "ARCHIVED") {
      archived.push(conv);
      continue;
    }
    if (conv.is_pinned) {
      pinned.push(conv);
      continue;
    }
    const ts = conv.last_message_at
      ? new Date(conv.last_message_at)
      : new Date(conv.created_at);
    if (ts >= todayStart) today.push(conv);
    else if (ts >= yesterdayStart) yesterday.push(conv);
    else if (ts >= weekStart) lastWeek.push(conv);
    else older.push(conv);
  }

  return { pinned, today, yesterday, lastWeek, older, archived };
}

function formatTime(isoStr: string | null): string {
  if (!isoStr) return "";
  const d = new Date(isoStr);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

// ─────────────────────────────────────────────────────────────────────────────
// Sub-component: Conversation Item
// ─────────────────────────────────────────────────────────────────────────────

interface ConvItemProps {
  conv: ConversationResponse;
  isActive: boolean;
  onSelect: (id: number) => void;
  onRename: (id: number, title: string) => void;
  onDelete: (id: number) => void;
  onArchive: (id: number) => void;
  onRestore: (id: number) => void;
  onPin: (id: number, pinned: boolean) => void;
}

function ConvItem({
  conv,
  isActive,
  onSelect,
  onRename,
  onDelete,
  onArchive,
  onRestore,
  onPin,
}: ConvItemProps) {
  const [editing, setEditing] = useState(false);
  const [editTitle, setEditTitle] = useState(conv.title || "");
  const [showActions, setShowActions] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editing && inputRef.current) inputRef.current.focus();
  }, [editing]);

  const commitRename = () => {
    const trimmed = editTitle.trim();
    if (trimmed && trimmed !== conv.title) {
      onRename(conv.id, trimmed);
    }
    setEditing(false);
  };

  const displayTitle = conv.title || "Untitled Conversation";

  return (
    <div
      className={cn(
        "group relative flex items-center gap-2 px-3 py-2 rounded-lg cursor-pointer transition-all text-xs select-none",
        isActive
          ? "bg-primary/15 text-primary border border-primary/20"
          : "hover:bg-muted/60 text-muted-foreground hover:text-foreground border border-transparent"
      )}
      onClick={() => !editing && onSelect(conv.id)}
      onMouseEnter={() => setShowActions(true)}
      onMouseLeave={() => setShowActions(false)}
    >
      {conv.is_pinned && (
        <Pin className="h-2.5 w-2.5 shrink-0 text-amber-500 fill-amber-500" />
      )}
      {!conv.is_pinned && (
        <MessageSquare className="h-3 w-3 shrink-0 opacity-50" />
      )}

      {editing ? (
        <div className="flex-1 flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
          <input
            ref={inputRef}
            value={editTitle}
            onChange={(e) => setEditTitle(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") commitRename();
              if (e.key === "Escape") setEditing(false);
            }}
            className="flex-1 bg-card border border-primary/30 rounded px-1.5 py-0.5 text-[11px] text-foreground outline-none min-w-0"
          />
          <button
            onClick={commitRename}
            className="text-emerald-500 hover:text-emerald-400 shrink-0"
          >
            <Check className="h-3 w-3" />
          </button>
          <button
            onClick={() => setEditing(false)}
            className="text-muted-foreground hover:text-foreground shrink-0"
          >
            <X className="h-3 w-3" />
          </button>
        </div>
      ) : (
        <span className="flex-1 truncate text-[11px] font-semibold leading-tight">
          {displayTitle}
        </span>
      )}

      {!editing && showActions && (
        <div
          className="absolute right-2 flex items-center gap-0.5"
          onClick={(e) => e.stopPropagation()}
        >
          <button
            title="Rename"
            onClick={() => {
              setEditTitle(conv.title || "");
              setEditing(true);
            }}
            className="p-1 rounded hover:bg-muted text-muted-foreground hover:text-foreground"
          >
            <Pencil className="h-2.5 w-2.5" />
          </button>
          <button
            title={conv.is_pinned ? "Unpin" : "Pin"}
            onClick={() => onPin(conv.id, !conv.is_pinned)}
            className="p-1 rounded hover:bg-muted text-muted-foreground hover:text-amber-500"
          >
            {conv.is_pinned ? (
              <PinOff className="h-2.5 w-2.5" />
            ) : (
              <Pin className="h-2.5 w-2.5" />
            )}
          </button>
          {conv.status === "ARCHIVED" ? (
            <button
              title="Restore"
              onClick={() => onRestore(conv.id)}
              className="p-1 rounded hover:bg-muted text-muted-foreground hover:text-emerald-500"
            >
              <ArchiveRestore className="h-2.5 w-2.5" />
            </button>
          ) : (
            <button
              title="Archive"
              onClick={() => onArchive(conv.id)}
              className="p-1 rounded hover:bg-muted text-muted-foreground hover:text-amber-500"
            >
              <Archive className="h-2.5 w-2.5" />
            </button>
          )}
          <button
            title="Delete"
            onClick={() => onDelete(conv.id)}
            className="p-1 rounded hover:bg-muted text-muted-foreground hover:text-rose-500"
          >
            <Trash2 className="h-2.5 w-2.5" />
          </button>
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Sub-component: Sidebar Group
// ─────────────────────────────────────────────────────────────────────────────

interface SidebarGroupProps {
  label: string;
  conversations: ConversationResponse[];
  activeId: number | null;
  onSelect: (id: number) => void;
  onRename: (id: number, title: string) => void;
  onDelete: (id: number) => void;
  onArchive: (id: number) => void;
  onRestore: (id: number) => void;
  onPin: (id: number, pinned: boolean) => void;
}

function SidebarGroup({
  label,
  conversations,
  activeId,
  onSelect,
  onRename,
  onDelete,
  onArchive,
  onRestore,
  onPin,
}: SidebarGroupProps) {
  const [collapsed, setCollapsed] = useState(false);

  if (conversations.length === 0) return null;

  return (
    <div className="space-y-0.5">
      <button
        onClick={() => setCollapsed((c) => !c)}
        className="flex items-center gap-1 w-full text-[9px] font-bold text-muted-foreground uppercase tracking-wider px-2 py-1 hover:text-foreground transition-colors"
      >
        <ChevronRight
          className={cn(
            "h-2.5 w-2.5 transition-transform",
            !collapsed && "rotate-90"
          )}
        />
        {label}
        <span className="ml-auto text-[8px] opacity-60">{conversations.length}</span>
      </button>
      {!collapsed && (
        <div className="space-y-0.5 pl-1">
          {conversations.map((conv) => (
            <ConvItem
              key={conv.id}
              conv={conv}
              isActive={conv.id === activeId}
              onSelect={onSelect}
              onRename={onRename}
              onDelete={onDelete}
              onArchive={onArchive}
              onRestore={onRestore}
              onPin={onPin}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Main Chat Page
// ─────────────────────────────────────────────────────────────────────────────

export default function ChatPage() {
  const { selectedKb, selectedKbId, knowledgeBases } = useKnowledgeBase();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [input, setInput] = useState("");
  const [generating, setGenerating] = useState(false);
  const [streamingMsgId, setStreamingMsgId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isBackendOnline, setIsBackendOnline] = useState(false);
  const [loading, setLoading] = useState(true);

  // Conversation state
  const [conversations, setConversations] = useState<ConversationResponse[]>([]);
  const [activeConvId, setActiveConvId] = useState<number | null>(null);
  const [convLoading, setConvLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [showArchived, setShowArchived] = useState(false);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  // ── Initial load ───────────────────────────────────────────────────────────

  useEffect(() => {
    async function init() {
      try {
        const [health, docs] = await Promise.all([
          HealthService.checkHealth(),
          DocumentsService.getDocuments(),
        ]);
        setIsBackendOnline(health.apiServer === "online");
        setDocuments(docs);
      } catch {
        setIsBackendOnline(false);
      } finally {
        setLoading(false);
      }
    }
    init();
  }, []);

  // ── Load conversations ─────────────────────────────────────────────────────

  const loadConversations = useCallback(async () => {
    setConvLoading(true);
    try {
      const res = await ConversationService.list({
        page: 1,
        page_size: 100,
        sort_by: "last_message_at",
      });
      setConversations(res.conversations);
    } catch (err) {
      console.error("Failed to load conversations", err);
    } finally {
      setConvLoading(false);
    }
  }, []);

  useEffect(() => {
    loadConversations();
  }, [loadConversations]);

  // ── Cleanup on unmount ─────────────────────────────────────────────────────

  useEffect(() => {
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, []);

  // ── Auto-scroll ────────────────────────────────────────────────────────────

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, generating]);

  // ── Conversation switching ─────────────────────────────────────────────────

  const handleSelectConversation = useCallback(async (id: number) => {
    if (generating) return;
    setActiveConvId(id);
    setMessages([]);
    setError(null);
    try {
      const detail = await ConversationService.get(id);
      const loaded: ChatMessage[] = detail.messages
        .filter((m) => m.role !== "system")
        .map((m) => ({
          id: String(m.id),
          role: m.role as "user" | "assistant",
          content: m.content,
          timestamp: new Date(m.created_at).toLocaleTimeString(),
          sources: (m.citations as ChatSource[] | null) ?? undefined,
        }));
      setMessages(loaded);
    } catch (err) {
      console.error("Failed to load conversation messages", err);
      setError("Failed to load conversation history.");
    }
  }, [generating]);

  // ── New conversation ───────────────────────────────────────────────────────

  const handleNewConversation = () => {
    setActiveConvId(null);
    setMessages([]);
    setError(null);
    setInput("");
  };

  // ── Stop generation ────────────────────────────────────────────────────────

  const handleStopGeneration = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setGenerating(false);
    setStreamingMsgId(null);
  };

  // ── Send message ───────────────────────────────────────────────────────────

  const handleSend = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || !selectedKbId || generating) return;

    const userMessageContent = input.trim();
    setInput("");
    setError(null);
    setGenerating(true);

    const userMsg: ChatMessage = {
      id: Math.random().toString(),
      role: "user",
      content: userMessageContent,
      timestamp: new Date().toLocaleTimeString(),
    };

    const assistantMsgId = Math.random().toString();
    const assistantMsg: ChatMessage = {
      id: assistantMsgId,
      role: "assistant",
      content: "",
      timestamp: new Date().toLocaleTimeString(),
    };

    setMessages((prev) => [...prev, userMsg, assistantMsg]);
    setStreamingMsgId(assistantMsgId);

    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      // If no active conversation, create one now.
      let convId = activeConvId;
      if (convId === null) {
        const newConv = await ConversationService.create(selectedKbId);
        convId = newConv.id;
        setActiveConvId(newConv.id);
        // Optimistically add to sidebar.
        setConversations((prev) => [newConv, ...prev]);
      }

      await ChatService.streamMessage(
        userMessageContent,
        selectedKbId,
        (chunk: string) => {
          setMessages((prev) =>
            prev.map((msg) =>
              msg.id === assistantMsgId
                ? { ...msg, content: msg.content + chunk }
                : msg
            )
          );
        },
        controller.signal,
        convId
      );

      // Refresh sidebar to update title + last_message_at.
      await loadConversations();

    } catch (err: any) {
      if (err.name === "AbortError") {
        console.log("Stream aborted by user.");
      } else {
        console.error("Chat error", err);
        setError(
          err.message ||
            "Failed to connect to ArabIQ AI service. Please ensure the backend FastAPI service is running."
        );
      }
    } finally {
      setGenerating(false);
      setStreamingMsgId(null);
      abortControllerRef.current = null;
    }
  };

  // ── Sidebar actions ────────────────────────────────────────────────────────

  const handleRename = useCallback(async (id: number, title: string) => {
    try {
      const updated = await ConversationService.rename(id, title);
      setConversations((prev) =>
        prev.map((c) => (c.id === id ? updated : c))
      );
    } catch (err) {
      console.error("Rename failed", err);
    }
  }, []);

  const handleDelete = useCallback(async (id: number) => {
    try {
      await ConversationService.delete(id);
      setConversations((prev) => prev.filter((c) => c.id !== id));
      if (activeConvId === id) {
        setActiveConvId(null);
        setMessages([]);
      }
    } catch (err) {
      console.error("Delete failed", err);
    }
  }, [activeConvId]);

  const handleArchive = useCallback(async (id: number) => {
    try {
      const updated = await ConversationService.archive(id);
      setConversations((prev) =>
        prev.map((c) => (c.id === id ? updated : c))
      );
    } catch (err) {
      console.error("Archive failed", err);
    }
  }, []);

  const handleRestore = useCallback(async (id: number) => {
    try {
      const updated = await ConversationService.restore(id);
      setConversations((prev) =>
        prev.map((c) => (c.id === id ? updated : c))
      );
    } catch (err) {
      console.error("Restore failed", err);
    }
  }, []);

  const handlePin = useCallback(async (id: number, pinned: boolean) => {
    try {
      const updated = await ConversationService.pin(id, pinned);
      setConversations((prev) =>
        prev.map((c) => (c.id === id ? updated : c))
      );
    } catch (err) {
      console.error("Pin failed", err);
    }
  }, []);

  // ── Filter conversations for sidebar ───────────────────────────────────────

  const filteredConversations = conversations.filter((c) => {
    if (!showArchived && c.status === "ARCHIVED") return false;
    if (showArchived && c.status !== "ARCHIVED") return false;
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      return (c.title || "Untitled Conversation").toLowerCase().includes(q);
    }
    return true;
  });

  const grouped = groupConversations(filteredConversations);

  // ── Loading screen ─────────────────────────────────────────────────────────

  if (loading) {
    return (
      <div className="flex h-[calc(100vh-8rem)] rounded-xl border border-border bg-card overflow-hidden shadow-sm items-center justify-center">
        <div className="flex flex-col items-center gap-2 text-xs text-muted-foreground font-semibold">
          <Loader2 className="h-6 w-6 animate-spin text-primary" />
          <span>Connecting to AI backend...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-[calc(100vh-8rem)] rounded-xl border border-border bg-card overflow-hidden shadow-sm animate-in fade-in duration-300">

      {/* ─────────────── Sidebar: Conversation History ─────────────── */}
      <div className="w-64 border-r border-border bg-muted/10 flex flex-col shrink-0 hidden md:flex">

        {/* Sidebar Header */}
        <div className="p-3 border-b border-border/60 flex items-center justify-between gap-2">
          <span className="text-[9px] font-bold text-muted-foreground uppercase tracking-wider">
            Conversations
          </span>
          <button
            onClick={handleNewConversation}
            title="New Conversation"
            className="flex items-center gap-1 text-[9px] font-bold px-2 py-1 rounded-md bg-primary/10 text-primary hover:bg-primary/20 border border-primary/15 transition-all"
          >
            <Plus className="h-2.5 w-2.5" />
            New
          </button>
        </div>

        {/* Search */}
        <div className="px-3 pt-2.5 pb-1">
          <div className="relative">
            <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-2.5 w-2.5 text-muted-foreground" />
            <input
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search conversations..."
              className="w-full pl-6 pr-2 py-1.5 bg-muted/40 border border-border rounded-md text-[10px] text-foreground placeholder:text-muted-foreground/60 outline-none focus:border-primary/30 transition-colors"
            />
          </div>
        </div>

        {/* Archive toggle */}
        <div className="px-3 py-1">
          <button
            onClick={() => setShowArchived((v) => !v)}
            className={cn(
              "text-[9px] font-bold flex items-center gap-1 px-2 py-0.5 rounded transition-colors",
              showArchived
                ? "text-amber-500 bg-amber-500/10"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            <Archive className="h-2.5 w-2.5" />
            {showArchived ? "← Active" : "Archived"}
          </button>
        </div>

        {/* Conversation List */}
        <div className="flex-1 overflow-y-auto px-2 py-1 space-y-3 scrollbar-thin">
          {convLoading ? (
            <div className="flex items-center justify-center py-8 gap-2 text-[10px] text-muted-foreground">
              <Loader2 className="h-3 w-3 animate-spin" />
              Loading...
            </div>
          ) : filteredConversations.length === 0 ? (
            <div className="text-center py-8 text-[10px] text-muted-foreground font-semibold space-y-1">
              <MessageSquare className="h-5 w-5 mx-auto opacity-30" />
              <p>{showArchived ? "No archived conversations." : "No conversations yet."}</p>
              {!showArchived && (
                <p className="text-[9px] opacity-70">
                  Start a chat to create one.
                </p>
              )}
            </div>
          ) : (
            <>
              <SidebarGroup
                label="Pinned"
                conversations={grouped.pinned}
                activeId={activeConvId}
                onSelect={handleSelectConversation}
                onRename={handleRename}
                onDelete={handleDelete}
                onArchive={handleArchive}
                onRestore={handleRestore}
                onPin={handlePin}
              />
              <SidebarGroup
                label="Today"
                conversations={grouped.today}
                activeId={activeConvId}
                onSelect={handleSelectConversation}
                onRename={handleRename}
                onDelete={handleDelete}
                onArchive={handleArchive}
                onRestore={handleRestore}
                onPin={handlePin}
              />
              <SidebarGroup
                label="Yesterday"
                conversations={grouped.yesterday}
                activeId={activeConvId}
                onSelect={handleSelectConversation}
                onRename={handleRename}
                onDelete={handleDelete}
                onArchive={handleArchive}
                onRestore={handleRestore}
                onPin={handlePin}
              />
              <SidebarGroup
                label="Last Week"
                conversations={grouped.lastWeek}
                activeId={activeConvId}
                onSelect={handleSelectConversation}
                onRename={handleRename}
                onDelete={handleDelete}
                onArchive={handleArchive}
                onRestore={handleRestore}
                onPin={handlePin}
              />
              <SidebarGroup
                label="Older"
                conversations={grouped.older}
                activeId={activeConvId}
                onSelect={handleSelectConversation}
                onRename={handleRename}
                onDelete={handleDelete}
                onArchive={handleArchive}
                onRestore={handleRestore}
                onPin={handlePin}
              />
              <SidebarGroup
                label="Archived"
                conversations={grouped.archived}
                activeId={activeConvId}
                onSelect={handleSelectConversation}
                onRename={handleRename}
                onDelete={handleDelete}
                onArchive={handleArchive}
                onRestore={handleRestore}
                onPin={handlePin}
              />
            </>
          )}
        </div>

        {/* Sidebar Footer */}
        <div className="p-3 border-t border-border/60 bg-muted/20 text-[9px] text-muted-foreground font-semibold flex items-center gap-1.5 justify-center">
          <Terminal className="h-3.5 w-3.5" />
          RAG Pipeline Enabled
        </div>
      </div>

      {/* ─────────────── Main Chat Workspace ─────────────── */}
      <div className="flex-1 flex flex-col justify-between bg-card min-w-0">

        {/* Top Header */}
        <div className="px-5 py-3.5 border-b border-border flex items-center justify-between gap-3 bg-muted/10 shrink-0">
          <div className="flex items-center gap-2 min-w-0">
            <Bot className="h-4.5 w-4.5 text-primary animate-pulse" />
            <span className="text-xs font-bold text-foreground truncate">
              ArabIQ Copilot
              {selectedKb ? ` — ${selectedKb.name}` : ""}
              {activeConvId
                ? ` · ${conversations.find((c) => c.id === activeConvId)?.title || "Conversation"}`
                : ""}
            </span>
          </div>

          <div
            className={cn(
              "flex items-center gap-1.5 text-[9px] font-bold px-2 py-0.5 rounded-full shrink-0 border",
              isBackendOnline
                ? "text-emerald-500 bg-emerald-500/10 border-emerald-500/10"
                : "text-amber-500 bg-amber-500/10 border-amber-500/10"
            )}
          >
            {!isBackendOnline && <Loader2 className="h-3 w-3 animate-spin" />}
            <span>{isBackendOnline ? "Connected" : "Offline / Connecting..."}</span>
          </div>
        </div>

        {/* Messages / Empty State */}
        {messages.length === 0 ? (
          <div className="flex-1 overflow-y-auto p-6 flex items-center justify-center">
            <div className="max-w-md w-full rounded-xl border border-border bg-card p-6 shadow-sm flex flex-col items-center text-center gap-4 animate-in fade-in duration-350">
              <div className="flex h-12 w-12 items-center justify-center rounded-full bg-primary/10 text-primary">
                <Bot className="h-6 w-6" />
              </div>

              <div className="space-y-1">
                <h3 className="text-sm font-bold text-foreground">
                  {activeConvId
                    ? "No messages yet — start the conversation"
                    : "Get Started with ArabIQ Copilot"}
                </h3>
                {!activeConvId && (
                  <p className="text-xs font-semibold text-primary">
                    Complete the workflow to start chatting:
                  </p>
                )}
              </div>

              {!activeConvId && (
                <div className="w-full text-left space-y-3.5 my-2">
                  {[
                    {
                      n: 1,
                      title: "Create a Knowledge Base",
                      desc: (
                        <>
                          Set up a security-isolated document segment in the{" "}
                          <Link href="/documents" className="underline hover:text-primary font-bold">
                            Documents Repository
                          </Link>
                          .
                        </>
                      ),
                    },
                    {
                      n: 2,
                      title: "Upload Documents",
                      desc: (
                        <>
                          Index your corporate assets on the{" "}
                          <Link href="/upload" className="underline hover:text-primary font-bold">
                            Upload Page
                          </Link>
                          .
                        </>
                      ),
                    },
                    {
                      n: 3,
                      title: "Wait for Processing",
                      desc: "The backend parses text, chunks content, and indexes vectors automatically.",
                    },
                    {
                      n: 4,
                      title: "Start Chatting",
                      desc: "Ask questions with full multi-turn context and grounded citations.",
                    },
                  ].map(({ n, title, desc }) => (
                    <div
                      key={n}
                      className="flex items-start gap-3 p-3 rounded-lg bg-muted/40 border border-border/40"
                    >
                      <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary/15 text-primary text-[10px] font-bold">
                        {n}
                      </span>
                      <div className="space-y-0.5">
                        <h4 className="text-xs font-bold text-foreground">{title}</h4>
                        <p className="text-[10px] text-muted-foreground leading-normal">
                          {desc}
                        </p>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              <div className="w-full border-t border-border/60 pt-3 text-[10px] text-left text-muted-foreground font-semibold space-y-2">
                <div className="flex items-center gap-2">
                  <Cpu className="h-3.5 w-3.5 text-primary shrink-0" />
                  <span>Ollama Inference (Data Residency Compliant)</span>
                </div>
                <div className="flex items-center gap-2">
                  <Lock className="h-3.5 w-3.5 text-primary shrink-0" />
                  <span>Bilingual Arabic-English RAG Translation</span>
                </div>
              </div>
            </div>
          </div>
        ) : (
          <div className="flex-1 overflow-y-auto p-6 space-y-4 bg-muted/5">
            {messages.map((msg) => (
              <div
                key={msg.id}
                className={cn(
                  "flex gap-3 text-xs font-semibold leading-relaxed max-w-3xl",
                  msg.role === "user" ? "ml-auto flex-row-reverse" : "mr-auto"
                )}
              >
                <div
                  className={cn(
                    "h-8 w-8 rounded-lg flex items-center justify-center shrink-0 border select-none",
                    msg.role === "user"
                      ? "bg-primary/10 text-primary border-primary/10"
                      : "bg-muted text-primary border-border"
                  )}
                >
                  {msg.role === "user" ? "👤" : "🤖"}
                </div>
                <div className="space-y-1.5 max-w-[85%]">
                  <div
                    className={cn(
                      "rounded-xl p-4 border shadow-xs whitespace-pre-wrap min-h-[44px]",
                      msg.role === "user"
                        ? "bg-primary text-primary-foreground border-primary"
                        : "bg-card text-foreground border-border"
                    )}
                  >
                    {msg.content}
                    {generating && msg.id === streamingMsgId && (
                      <span className="inline-block font-mono text-primary animate-pulse ml-0.5 select-none font-bold">
                        ▋
                      </span>
                    )}
                  </div>

                  {msg.role === "assistant" &&
                    msg.sources &&
                    msg.sources.length > 0 && (
                      <div className="space-y-2 mt-3.5 pl-1 w-full">
                        <span className="text-[9px] font-bold uppercase tracking-wider text-muted-foreground block">
                          Grounded Citations &amp; Sources
                        </span>
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 max-w-xl">
                          {msg.sources.map((src, idx) => {
                            const matchedDoc = documents.find(
                              (d) => d.parsedDocId === src.parsed_document_id
                            );
                            const filename = matchedDoc
                              ? matchedDoc.name
                              : `Document #${src.parsed_document_id}`;
                            const relevance = (src.score * 100).toFixed(0);

                            return (
                              <div
                                key={idx}
                                className="rounded-lg border border-border bg-muted/20 p-3 flex flex-col justify-between gap-3 text-[11px] shadow-xs group hover:border-primary/25 transition-all"
                              >
                                <div className="space-y-1">
                                  <div
                                    className="flex items-center gap-1.5 font-bold text-foreground truncate"
                                    title={filename}
                                  >
                                    <span className="text-muted-foreground shrink-0 select-none">
                                      📄
                                    </span>
                                    <span className="truncate">{filename}</span>
                                  </div>
                                  <div className="flex items-center gap-2 mt-1">
                                    <span className="text-[9px] font-bold text-emerald-500 bg-emerald-500/5 px-2 py-0.5 rounded-md border border-emerald-500/10">
                                      Relevance: {relevance}%
                                    </span>
                                  </div>
                                </div>
                                <button
                                  disabled
                                  className="w-full text-center py-1.5 bg-muted text-muted-foreground/60 border border-border/80 rounded-md font-bold text-[9px] uppercase tracking-wider cursor-not-allowed"
                                >
                                  View Source (Disabled)
                                </button>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    )}
                </div>
              </div>
            ))}

            <div ref={messagesEndRef} />
          </div>
        )}

        {/* Input Form */}
        <form
          onSubmit={handleSend}
          className="p-4 border-t border-border bg-card flex flex-col gap-2 shrink-0"
        >
          {error && (
            <div className="flex items-center gap-2 p-2.5 rounded-lg border border-destructive/20 bg-destructive/10 text-destructive text-[11px] font-semibold mb-1">
              <AlertTriangle className="h-4 w-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          <div className="flex gap-2">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value.slice(0, 4000))}
              disabled={!selectedKbId || generating}
              placeholder={
                !selectedKbId
                  ? "Select a Knowledge Base in folders/upload to start..."
                  : activeConvId
                  ? "Continue the conversation... (Shift+Enter for new line)"
                  : "Ask questions about your uploaded documents... (Max 4000 characters)"
              }
              rows={1}
              autoFocus
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  const form = e.currentTarget.form;
                  if (form) form.requestSubmit();
                }
              }}
              className={cn(
                "flex-1 bg-muted/40 border border-border rounded-lg px-3 py-2 text-xs font-semibold outline-none text-foreground placeholder:text-muted-foreground/60 w-full resize-none min-h-[38px] max-h-[120px] py-2.5",
                (!selectedKbId || generating) && "cursor-not-allowed text-muted-foreground"
              )}
            />
            {generating ? (
              <button
                type="button"
                onClick={handleStopGeneration}
                title="Stop Generation"
                className="flex h-9.5 px-3 shrink-0 items-center justify-center rounded-lg font-semibold text-xs transition-all bg-rose-500/10 text-rose-500 hover:bg-rose-500/20 border border-rose-500/20 cursor-pointer gap-1.5"
              >
                <Square className="h-3.5 w-3.5 fill-current" />
                <span>Stop</span>
              </button>
            ) : (
              <button
                type="submit"
                disabled={!selectedKbId || !input.trim()}
                className={cn(
                  "flex h-9.5 w-9.5 shrink-0 items-center justify-center rounded-lg font-semibold text-xs transition-all",
                  !selectedKbId || !input.trim()
                    ? "bg-primary/20 text-primary-foreground/50 cursor-not-allowed"
                    : "bg-primary text-primary-foreground hover:bg-primary/95 cursor-pointer shadow-md shadow-primary/10"
                )}
              >
                <Send className="h-4 w-4" />
              </button>
            )}
          </div>
          <div className="text-center text-[9px] text-slate-500 font-semibold uppercase tracking-wider">
            ArabIQ Grounded RAG Pipeline active
            {activeConvId && (
              <span className="ml-2 text-primary/70">· Conversational Memory On</span>
            )}
          </div>
        </form>
      </div>
    </div>
  );
}