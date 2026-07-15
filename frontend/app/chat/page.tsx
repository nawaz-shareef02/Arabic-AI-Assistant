"use client";

import React, { useState, useEffect, useRef } from "react";
import { ChatService, ChatMessage, ChatSource } from "@/services/chat";
import { useKnowledgeBase } from "@/context/KnowledgeBaseContext";
import { HealthService } from "@/services/health";
import { DocumentsService, DocumentItem } from "@/services/documents";
import { 
  Send, 
  Cpu, 
  AlertTriangle, 
  MessageSquare,
  Bot,
  Terminal,
  Lock,
  Loader2
} from "lucide-react";
import { cn } from "@/lib/utils";
import Link from "next/link";

export default function ChatPage() {
  const { selectedKb, selectedKbId, knowledgeBases } = useKnowledgeBase();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [input, setInput] = useState("");
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isBackendOnline, setIsBackendOnline] = useState(false);
  const [loading, setLoading] = useState(true);

  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Check health and initialize
  useEffect(() => {
    async function initChat() {
      try {
        const [health, docs] = await Promise.all([
          HealthService.checkHealth(),
          DocumentsService.getDocuments()
        ]);
        setIsBackendOnline(health.apiServer === "online");
        setDocuments(docs);
      } catch (err) {
        setIsBackendOnline(false);
      } finally {
        setLoading(false);
      }
    }
    initChat();
  }, []);

  // Auto-scroll to latest message
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, generating]);

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
      timestamp: new Date().toLocaleTimeString()
    };

    setMessages((prev) => [...prev, userMsg]);

    try {
      const response = await ChatService.sendMessage(userMessageContent, selectedKbId);
      
      const assistantMsg: ChatMessage = {
        id: Math.random().toString(),
        role: "assistant",
        content: response.answer,
        timestamp: new Date().toLocaleTimeString(),
        sources: response.sources
      };
      
      setMessages((prev) => [...prev, assistantMsg]);
    } catch (err: any) {
      console.error("Chat error", err);
      let friendlyMsg = "Failed to connect to ArabIQ AI service. Please ensure the backend FastAPI service is running.";
      if (err.response) {
        if (err.response.status === 404) {
          friendlyMsg = "The target Knowledge Base was not found on the server. Please verify it exists.";
        } else if (err.response.status === 500) {
          friendlyMsg = "Internal AI engine error. Ollama or Qdrant might be offline or out of memory.";
        } else if (err.response.data?.detail) {
          friendlyMsg = typeof err.response.data.detail === "string" ? err.response.data.detail : JSON.stringify(err.response.data.detail);
        }
      }
      setError(friendlyMsg);
    } finally {
      setGenerating(false);
    }
  };

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
      {/* Sidebar: Chat History (Simplified for Sprint 9) */}
      <div className="w-64 border-r border-border bg-muted/10 flex flex-col justify-between shrink-0 hidden md:flex">
        <div className="p-4 flex-1 flex flex-col gap-4">
          <div className="flex items-center justify-between border-b border-border/60 pb-2">
            <span className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider">Active Configuration</span>
          </div>
          
          <div className="space-y-3">
            <div className="rounded-lg border border-border bg-card p-3 space-y-2">
              <span className="text-[9px] font-bold text-primary uppercase tracking-wider block">Target Knowledge Base</span>
              {selectedKb ? (
                <div className="space-y-1">
                  <span className="text-xs font-bold text-foreground block truncate">{selectedKb.name}</span>
                  <span className="text-[10px] text-muted-foreground block">Documents: {selectedKb.docsCount}</span>
                </div>
              ) : (
                <span className="text-xs text-muted-foreground italic">None selected. Go to Documents to create one.</span>
              )}
            </div>

            <div className="rounded-lg border border-border bg-card p-3 space-y-1 text-[10px] text-muted-foreground font-semibold">
              <span className="text-[9px] font-bold text-primary uppercase tracking-wider block mb-1">Status Panel</span>
              <div className="flex items-center justify-between">
                <span>FastAPI Server:</span>
                <span className={cn("font-bold", isBackendOnline ? "text-emerald-500" : "text-rose-500")}>
                  {isBackendOnline ? "Online" : "Offline"}
                </span>
              </div>
            </div>
          </div>
        </div>

        <div className="p-4 border-t border-border/60 bg-muted/20 text-[9px] text-muted-foreground font-semibold flex items-center gap-1.5 justify-center">
          <Terminal className="h-3.5 w-3.5" />
          RAG Pipeline Enabled
        </div>
      </div>

      {/* Main Chat Workspace */}
      <div className="flex-1 flex flex-col justify-between bg-card min-w-0">
        {/* Top Header status */}
        <div className="px-5 py-3.5 border-b border-border flex items-center justify-between gap-3 bg-muted/10 shrink-0">
          <div className="flex items-center gap-2 min-w-0">
            <Bot className="h-4.5 w-4.5 text-primary animate-pulse" />
            <span className="text-xs font-bold text-foreground truncate">
              ArabIQ Copilot {selectedKb ? `— ${selectedKb.name}` : ""}
            </span>
          </div>
          
          <div className={cn(
            "flex items-center gap-1.5 text-[9px] font-bold px-2 py-0.5 rounded-full shrink-0 border",
            isBackendOnline 
              ? "text-emerald-500 bg-emerald-500/10 border-emerald-500/10" 
              : "text-amber-500 bg-amber-500/10 border-amber-500/10"
          )}>
            {!isBackendOnline && <Loader2 className="h-3 w-3 animate-spin" />}
            <span>{isBackendOnline ? "Connected" : "Offline / Connecting..."}</span>
          </div>
        </div>

        {/* Center Panel: Messages or Empty State */}
        {messages.length === 0 ? (
          <div className="flex-1 overflow-y-auto p-6 flex items-center justify-center">
            <div className="max-w-md w-full rounded-xl border border-border bg-card p-6 shadow-sm flex flex-col items-center text-center gap-4 animate-in fade-in duration-350">
              <div className="flex h-12 w-12 items-center justify-center rounded-full bg-primary/10 text-primary">
                <Bot className="h-6 w-6" />
              </div>
              
              <div className="space-y-1">
                <h3 className="text-sm font-bold text-foreground">Get Started with ArabIQ Copilot</h3>
                <p className="text-xs font-semibold text-primary">Complete the workflow to start chatting:</p>
              </div>

              <div className="w-full text-left space-y-3.5 my-2">
                <div className="flex items-start gap-3 p-3 rounded-lg bg-muted/40 border border-border/40">
                  <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary/15 text-primary text-[10px] font-bold">1</span>
                  <div className="space-y-0.5">
                    <h4 className="text-xs font-bold text-foreground">Create a Knowledge Base</h4>
                    <p className="text-[10px] text-muted-foreground leading-normal">
                      Set up a security-isolated document segment in the{" "}
                      <Link href="/documents" className="underline hover:text-primary font-bold">
                        Documents Repository
                      </Link>.
                    </p>
                  </div>
                </div>

                <div className="flex items-start gap-3 p-3 rounded-lg bg-muted/40 border border-border/40">
                  <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary/15 text-primary text-[10px] font-bold">2</span>
                  <div className="space-y-0.5">
                    <h4 className="text-xs font-bold text-foreground">Upload Documents</h4>
                    <p className="text-[10px] text-muted-foreground leading-normal">
                      Index your corporate assets on the{" "}
                      <Link href="/upload" className="underline hover:text-primary font-bold">
                        Upload Page
                      </Link>.
                    </p>
                  </div>
                </div>

                <div className="flex items-start gap-3 p-3 rounded-lg bg-muted/40 border border-border/40">
                  <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary/15 text-primary text-[10px] font-bold">3</span>
                  <div className="space-y-0.5">
                    <h4 className="text-xs font-bold text-foreground">Wait for Processing</h4>
                    <p className="text-[10px] text-muted-foreground leading-normal">
                      The backend parses text, chunks content, and indexes vectors automatically.
                    </p>
                  </div>
                </div>

                <div className="flex items-start gap-3 p-3 rounded-lg bg-muted/40 border border-border/40">
                  <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary/15 text-primary text-[10px] font-bold">4</span>
                  <div className="space-y-0.5">
                    <h4 className="text-xs font-bold text-foreground">Start Chatting</h4>
                    <p className="text-[10px] text-muted-foreground leading-normal">
                      Ask questions and generate citations referencing the selected active Knowledge Base.
                    </p>
                  </div>
                </div>
              </div>

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
                <div className={cn(
                  "h-8 w-8 rounded-lg flex items-center justify-center shrink-0 border select-none",
                  msg.role === "user" 
                    ? "bg-primary/10 text-primary border-primary/10" 
                    : "bg-muted text-primary border-border"
                )}>
                  {msg.role === "user" ? "👤" : "🤖"}
                </div>
                <div className="space-y-1.5 max-w-[85%]">
                  <div className={cn(
                    "rounded-xl p-4 border shadow-xs whitespace-pre-wrap",
                    msg.role === "user" 
                      ? "bg-primary text-primary-foreground border-primary" 
                      : "bg-card text-foreground border-border"
                  )}>
                    {msg.content}
                  </div>
                  
                  {msg.role === "assistant" && msg.sources && msg.sources.length > 0 && (
                    <div className="space-y-2 mt-3.5 pl-1 w-full">
                      <span className="text-[9px] font-bold uppercase tracking-wider text-muted-foreground block">
                        Grounded Citations & Sources
                      </span>
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 max-w-xl">
                        {msg.sources.map((src, idx) => {
                          const matchedDoc = documents.find(d => d.parsedDocId === src.parsed_document_id);
                          const filename = matchedDoc ? matchedDoc.name : `Document #${src.parsed_document_id}`;
                          const relevance = (src.score * 100).toFixed(0);
                          
                          return (
                            <div key={idx} className="rounded-lg border border-border bg-muted/20 p-3 flex flex-col justify-between gap-3 text-[11px] shadow-xs group hover:border-primary/25 transition-all">
                              <div className="space-y-1">
                                <div className="flex items-center gap-1.5 font-bold text-foreground truncate" title={filename}>
                                  <span className="text-muted-foreground shrink-0 select-none">📄</span>
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
                                className="w-full text-center py-1.5 bg-muted text-muted-foreground/60 border border-border/80 rounded-md font-bold text-[9px] uppercase tracking-wider cursor-not-allowed hover:bg-muted transition-all"
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
            
            {generating && (
              <div className="flex gap-3 text-xs font-semibold leading-relaxed mr-auto w-full max-w-2xl">
                <div className="h-8 w-8 rounded-lg flex items-center justify-center shrink-0 border bg-muted text-primary border-border select-none">
                  🤖
                </div>
                <div className="space-y-3.5 flex-1 max-w-[85%]">
                  <div className="rounded-xl p-4 border bg-card border-border shadow-xs space-y-2.5 animate-pulse">
                    <div className="flex items-center gap-2 text-primary font-bold text-[10px] uppercase tracking-wider mb-1">
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      <span>ArabIQ Copilot is generating grounded response...</span>
                    </div>
                    <div className="h-4 bg-slate-200 dark:bg-zinc-800 rounded-md w-full" />
                    <div className="h-4 bg-slate-200 dark:bg-zinc-800 rounded-md w-11/12" />
                    <div className="h-4 bg-slate-200 dark:bg-zinc-800 rounded-md w-3/4" />
                  </div>
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>
        )}

        {/* Bottom Message Input Form */}
        <form onSubmit={handleSend} className="p-4 border-t border-border bg-card flex flex-col gap-2 shrink-0">
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
                  : "Ask questions about your uploaded documents... (Max 4000 characters)"
              }
              rows={1}
              autoFocus
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  // Trigger form submit or handleSend manually
                  const form = e.currentTarget.form;
                  if (form) {
                    form.requestSubmit();
                  }
                }
              }}
              className={cn(
                "flex-1 bg-muted/40 border border-border rounded-lg px-3 py-2 text-xs font-semibold outline-none text-foreground placeholder:text-muted-foreground/60 w-full resize-none min-h-[38px] max-h-[120px] py-2.5",
                (!selectedKbId || generating) && "cursor-not-allowed text-muted-foreground"
              )}
            />
            <button
              type="submit"
              disabled={!selectedKbId || !input.trim() || generating}
              className={cn(
                "flex h-9.5 w-9.5 shrink-0 items-center justify-center rounded-lg font-semibold text-xs transition-all",
                (!selectedKbId || !input.trim() || generating)
                  ? "bg-primary/20 text-primary-foreground/50 cursor-not-allowed"
                  : "bg-primary text-primary-foreground hover:bg-primary/95 cursor-pointer shadow-md shadow-primary/10"
              )}
            >
              {generating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
            </button>
          </div>
          <div className="text-center text-[9px] text-slate-500 font-semibold uppercase tracking-wider">
            ArabIQ Grounded RAG Pipeline active
          </div>
        </form>
      </div>
    </div>
  );
}