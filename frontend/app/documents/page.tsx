"use client";

import React, { useState, useEffect, useRef } from "react";
import { DocumentsService, DocumentItem } from "@/services/documents";
import { useKnowledgeBase } from "@/context/KnowledgeBaseContext";
import {
  Search,
  Plus,
  Database,
  FolderOpen,
  Upload,
  ServerOff,
  Loader2
} from "lucide-react";
import { cn } from "@/lib/utils";
import Link from "next/link";

export default function DocumentsPage() {
  const [activeTab, setActiveTab] = useState<"files" | "kbs">("files");
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const { knowledgeBases, createKnowledgeBase, deleteKnowledgeBase, refreshKnowledgeBases } = useKnowledgeBase();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filter States
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedKbFilter, setSelectedKbFilter] = useState("All");
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newKBName, setNewKBName] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const delayRef = useRef<number>(2500);

  useEffect(() => {
    async function loadData() {
      try {
        const docs = await DocumentsService.getDocuments();
        setDocuments(docs);
        refreshKnowledgeBases();
      } catch (err) {
        console.error("Failed to load documents data:", err);
      } finally {
        setLoading(false);
      }
    }
    loadData();
  }, []);

  // Polling for processing status of documents using recursive setTimeout & backoff
  useEffect(() => {
    const activePolling = documents.some(
      (doc) => doc.status === "Queued" || doc.status === "Uploaded" || doc.status === "Parsing"
    );

    if (!activePolling) {
      delayRef.current = 2500;
      return;
    }

    let timer: NodeJS.Timeout;

    async function poll() {
      try {
        const docs = await DocumentsService.getDocuments();
        setDocuments(docs);
        refreshKnowledgeBases();
        delayRef.current = Math.min(delayRef.current + 1500, 10000);
        timer = setTimeout(poll, delayRef.current);
      } catch (err) {
        console.error("Error polling documents:", err);
        delayRef.current = Math.min(delayRef.current + 2000, 10000);
        timer = setTimeout(poll, delayRef.current);
      }
    }

    timer = setTimeout(poll, delayRef.current);
    return () => clearTimeout(timer);
  }, [documents]);

  const handleCreateKB = async () => {
    if (!newKBName.trim()) return;
    setIsSubmitting(true);
    setError(null);
    try {
      await createKnowledgeBase(newKBName);
      setNewKBName("");
      setShowCreateModal(false);
    } catch (err: any) {
      setError(err.message || "Failed to create knowledge base.");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDeleteKB = async (uuid: string) => {
    if (!confirm("Are you sure you want to delete this knowledge base? This action cannot be undone.")) return;
    try {
      await deleteKnowledgeBase(uuid);
    } catch (err: any) {
      alert("Failed to delete knowledge base: " + (err.message || err));
    }
  };

  const handleDeleteDocument = async (id: string) => {
    if (!confirm("Are you sure you want to delete this document?")) return;
    try {
      await DocumentsService.deleteDocument(id);
      setDocuments((prev) => prev.filter((doc) => doc.id !== id));
    } catch (err: any) {
      alert("Failed to delete document: " + (err.message || err));
    }
  };

  const filteredDocuments = documents.filter((doc) => {
    const matchesSearch = doc.name.toLowerCase().includes(searchQuery.toLowerCase());
    const matchesKb = selectedKbFilter === "All" || doc.kb === selectedKbFilter;
    return matchesSearch && matchesKb;
  });


  if (loading) {
    return (
      <div className="space-y-6 max-w-7xl mx-auto">
        <div className="flex justify-between items-center">
          <div className="space-y-2">
            <div className="h-7 w-48 bg-slate-200 dark:bg-zinc-800 rounded-md animate-pulse" />
            <div className="h-4 w-72 bg-slate-200 dark:bg-zinc-800 rounded-md animate-pulse" />
          </div>
          <div className="h-9 w-40 bg-slate-200 dark:bg-zinc-800 rounded-lg animate-pulse" />
        </div>
        
        {/* Table Skeleton */}
        <div className="rounded-xl border border-border bg-card overflow-hidden">
          <div className="h-10 bg-muted/40 border-b border-border flex items-center px-6 gap-4">
            <div className="h-4 w-1/3 bg-slate-200 dark:bg-zinc-800 rounded-md animate-pulse" />
            <div className="h-4 w-1/6 bg-slate-200 dark:bg-zinc-800 rounded-md animate-pulse" />
            <div className="h-4 w-1/12 bg-slate-200 dark:bg-zinc-800 rounded-md animate-pulse" />
            <div className="h-4 w-1/12 bg-slate-200 dark:bg-zinc-800 rounded-md animate-pulse" />
            <div className="h-4 w-16 bg-slate-200 dark:bg-zinc-800 rounded-md animate-pulse ml-auto" />
          </div>
          <div className="divide-y divide-border/40 px-6">
            {[1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="py-4.5 flex items-center gap-4">
                <div className="h-4.5 w-1/3 bg-slate-200 dark:bg-zinc-800 rounded-md animate-pulse" />
                <div className="h-4 w-1/6 bg-slate-200 dark:bg-zinc-800 rounded-md animate-pulse" />
                <div className="h-4 w-1/12 bg-slate-200 dark:bg-zinc-800 rounded-md animate-pulse" />
                <div className="h-4 w-1/12 bg-slate-200 dark:bg-zinc-800 rounded-md animate-pulse" />
                <div className="h-6 w-16 bg-slate-200 dark:bg-zinc-800 rounded-full animate-pulse ml-auto" />
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-7xl mx-auto animate-in fade-in duration-300">
      {/* Header section */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h1 className="text-xl font-bold text-foreground">Document Repository</h1>
          <p className="text-xs text-muted-foreground mt-1">
            Manage your indexed folders, upload documents, and review chunks extracted for RAG searches.
          </p>
        </div>
        <div className="flex items-center gap-3 bg-muted/40 p-1 rounded-lg border border-border">
          <button
            onClick={() => setActiveTab("files")}
            className={cn(
              "px-3 py-1.5 rounded-md text-[11px] font-bold transition-all cursor-pointer",
              activeTab === "files" ? "bg-card text-foreground shadow-xs" : "text-muted-foreground hover:text-foreground"
            )}
          >
            All Files
          </button>
          <button
            onClick={() => setActiveTab("kbs")}
            className={cn(
              "px-3 py-1.5 rounded-md text-[11px] font-bold transition-all cursor-pointer",
              activeTab === "kbs" ? "bg-card text-foreground shadow-xs" : "text-muted-foreground hover:text-foreground"
            )}
          >
            Knowledge Bases
          </button>
        </div>
      </div>

      {activeTab === "files" ? (
        <div className="space-y-4">
          {/* Controls bar */}
          <div className="flex flex-col md:flex-row gap-3 bg-card p-4 rounded-xl border border-border/80 shadow-xs">
            {/* Search Input */}
            <div className="relative flex-1">
              <Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
              <input
                type="text"
                placeholder="Search documents by filename..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="pl-9 w-full bg-muted/20 border border-border rounded-lg py-2 text-xs font-semibold focus:outline-hidden text-foreground placeholder:text-muted-foreground/60"
              />
            </div>

            {/* KB Dropdown filter */}
            <div className="flex items-center gap-2">
              <span className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider hidden lg:inline">Knowledge Base:</span>
              <select
                value={selectedKbFilter}
                onChange={(e) => setSelectedKbFilter(e.target.value)}
                className="bg-card border border-border rounded-lg px-3 py-2 text-xs font-semibold focus:outline-hidden text-foreground"
              >
                <option value="All">All KBs</option>
                {knowledgeBases.map((kb) => (
                  <option key={kb.id} value={kb.uuid}>{kb.name}</option>
                ))}
              </select>
            </div>
          </div>

          {/* Table display */}
          {filteredDocuments.length === 0 ? (
            <div className="rounded-xl border border-border/80 bg-card overflow-hidden shadow-xs flex flex-col items-center justify-center p-16 text-center gap-4">
              <div className="flex h-14 w-14 items-center justify-center rounded-full bg-slate-100 dark:bg-zinc-800 text-slate-400 dark:text-zinc-500">
                <FolderOpen className="h-7 w-7" />
              </div>
              
              <div className="space-y-1">
                <h3 className="text-sm font-bold text-foreground">
                  {searchQuery || selectedKbFilter !== "All" ? "No matching documents" : "No Documents Uploaded"}
                </h3>
                <p className="text-xs text-muted-foreground max-w-xs leading-relaxed">
                  {searchQuery || selectedKbFilter !== "All" 
                    ? "Try adjusting your search filters to find what you're looking for." 
                    : "Upload your first PDF, DOCX or TXT file to start indexing corporate knowledge."}
                </p>
              </div>

              {!(searchQuery || selectedKbFilter !== "All") && (
                <Link
                  href="/upload"
                  className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-primary hover:bg-primary/95 text-primary-foreground text-xs font-semibold shadow-md transition-all mt-2"
                >
                  <Upload className="h-4 w-4" />
                  <span>Upload Document</span>
                </Link>
              )}
            </div>
          ) : (
            <div className="rounded-xl border border-border bg-card overflow-hidden shadow-xs">
              <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse text-xs">
                  <thead>
                    <tr className="border-b border-border/60 bg-muted/20 text-muted-foreground uppercase font-bold text-[9px] tracking-wider">
                      <th className="p-3.5 pl-5">Filename</th>
                      <th className="p-3.5">Knowledge Base</th>
                      <th className="p-3.5">Language</th>
                      <th className="p-3.5">Size</th>
                      <th className="p-3.5">Chunks</th>
                      <th className="p-3.5">Status</th>
                      <th className="p-3.5">Date Added</th>
                      <th className="p-3.5 pr-5 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border/30">
                    {filteredDocuments.map((doc) => {
                      const parentKb = knowledgeBases.find(k => k.uuid === doc.kb);
                      return (
                        <tr key={doc.id} className="hover:bg-muted/10 transition-all font-semibold">
                          <td className="p-3.5 pl-5 text-foreground font-bold">
                            <div>{doc.name}</div>
                            {doc.status === "Failed" && doc.errorDetail && (
                              <div className="text-[10px] text-rose-500 font-semibold mt-0.5">
                                Reason: {doc.errorDetail}
                              </div>
                            )}
                            {doc.status === "Parsed" && doc.parserName && (
                              <div className="text-[10px] text-muted-foreground font-normal mt-0.5">
                                {doc.parserName} • {doc.pages ?? 0} pages • {doc.characters ?? 0} chars • {doc.processingTime ?? 0}s
                              </div>
                            )}
                          </td>
                          <td className="p-3.5 text-muted-foreground">{parentKb ? parentKb.name : "Unknown"}</td>
                          <td className="p-3.5">
                            <span className={`px-2 py-0.5 rounded-full text-[9px] font-bold ${
                              doc.lang === "AR" 
                                ? "bg-emerald-500/10 text-emerald-500 border border-emerald-500/10" 
                                : doc.lang === "Bilingual"
                                ? "bg-indigo-500/10 text-indigo-500 border border-indigo-500/10"
                                : "bg-blue-500/10 text-blue-500 border border-blue-500/10"
                            }`}>
                              {doc.lang}
                            </span>
                          </td>
                          <td className="p-3.5 text-muted-foreground">{doc.size}</td>
                          <td className="p-3.5 text-foreground">{doc.status === "Parsed" ? doc.chunks : "—"}</td>
                          <td className="p-3.5">
                            <span className={cn(
                              "px-2 py-0.5 rounded-full text-[9px] font-bold border",
                              doc.status === "Parsed"
                                ? "bg-emerald-500/10 text-emerald-500 border-emerald-500/10"
                                : doc.status === "Failed"
                                ? "bg-rose-500/10 text-rose-500 border-rose-500/10"
                                : doc.status === "Parsing"
                                ? "bg-orange-500/10 text-orange-500 border-orange-500/10 animate-pulse"
                                : doc.status === "Uploaded"
                                ? "bg-blue-500/10 text-blue-500 border-blue-500/10"
                                : "bg-slate-500/10 text-slate-500 border-slate-500/10"
                            )}>
                              {doc.status}
                            </span>
                          </td>
                          <td className="p-3.5 text-muted-foreground">{doc.date}</td>
                          <td className="p-3.5 pr-5 text-right">
                            <button
                              onClick={() => handleDeleteDocument(doc.id)}
                              className="text-rose-500 hover:text-rose-600 font-bold hover:underline cursor-pointer"
                            >
                              Delete
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>

      ) : (
        <div className="space-y-6">
          {/* KB management toolbar */}
          <div className="flex items-center justify-between border-b border-border pb-4">
            <div>
              <h2 className="text-sm font-bold text-foreground">Knowledge Base Collections</h2>
              <p className="text-[11px] text-muted-foreground mt-0.5">Clustered documents partition databases used for retrieval context.</p>
            </div>
            <button
              onClick={() => setShowCreateModal(true)}
              className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-primary text-primary-foreground text-xs font-semibold hover:bg-primary/95 transition-all shadow-md cursor-pointer"
            >
              <Plus className="h-4 w-4" />
              Create Knowledge Base
            </button>
          </div>

          {/* List display or empty state */}
          {knowledgeBases.length === 0 ? (
            <div className="rounded-xl border border-border/80 bg-card p-12 text-center flex flex-col items-center justify-center gap-4 animate-in fade-in duration-200">
              <div className="flex h-14 w-14 items-center justify-center rounded-full bg-slate-100 dark:bg-zinc-800 text-slate-400 dark:text-zinc-500">
                <Database className="h-7 w-7" />
              </div>

              <div className="space-y-1">
                <h3 className="text-sm font-bold text-foreground">No Knowledge Bases</h3>
                <p className="text-xs text-muted-foreground max-w-xs leading-relaxed">
                  Create a knowledge base to group and isolate documents by topic, project, or department rules.
                </p>
              </div>

              <button
                onClick={() => setShowCreateModal(true)}
                className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-primary hover:bg-primary/95 text-primary-foreground text-xs font-semibold shadow-md transition-all mt-2 cursor-pointer"
              >
                <Plus className="h-4 w-4" />
                <span>Create Your First Knowledge Base</span>
              </button>
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
              {knowledgeBases.map((kb) => {
                const kbDocCount = documents.filter((doc) => doc.kb === kb.uuid).length;
                return (
                  <div key={kb.id} className="rounded-xl border border-border bg-card p-5 shadow-xs hover:border-primary/50 transition-all flex flex-col justify-between min-h-[140px] relative overflow-hidden group">
                    <div className="space-y-3">
                      <div className="flex items-start justify-between gap-3">
                        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/10 text-primary border border-primary/10">
                          <Database className="h-4.5 w-4.5" />
                        </div>
                        <button
                          onClick={() => handleDeleteKB(kb.uuid)}
                          className="text-[10px] font-bold text-rose-500 hover:text-rose-600 bg-rose-500/10 border border-rose-500/10 px-2 py-0.5 rounded-full transition-all cursor-pointer"
                        >
                          Delete
                        </button>
                      </div>
                      <div>
                        <h4 className="text-sm font-bold text-foreground truncate">{kb.name}</h4>
                        <p className="text-[10px] text-muted-foreground mt-0.5">Created on {kb.date}</p>
                      </div>
                    </div>
                    
                    <div className="flex items-center justify-between border-t border-border/30 pt-3.5 mt-4 text-[10px] font-bold">
                      <span className="text-muted-foreground">Documents: <span className="text-foreground">{kbDocCount}</span></span>
                      <span className="text-muted-foreground">Owner: <span className="text-foreground">{kb.owner}</span></span>
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {/* Create KB Modal */}
          {showCreateModal && (
            <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
              <div className="fixed inset-0 bg-background/80 backdrop-blur-xs" onClick={() => setShowCreateModal(false)} />

              <div className="relative w-full max-w-sm rounded-xl border border-border bg-popover text-popover-foreground shadow-2xl p-5 overflow-hidden animate-in fade-in zoom-in-95 duration-200">
                <h3 className="text-sm font-bold text-foreground mb-1">Create Knowledge Base</h3>
                <p className="text-[11px] text-muted-foreground mb-4">Provide a clear department or topic identifier for this KB segment.</p>

                {error && (
                  <div className="flex items-center gap-2 p-3 rounded-lg border border-destructive/20 bg-destructive/10 text-destructive text-[11px] font-semibold mb-4">
                    <ServerOff className="h-4 w-4 shrink-0" />
                    <span>{error}</span>
                  </div>
                )}

                <div className="space-y-4">
                  <input
                    type="text"
                    placeholder="e.g., Legal Agreements"
                    value={newKBName}
                    onChange={(e) => setNewKBName(e.target.value)}
                    disabled={isSubmitting}
                    className="w-full bg-muted/40 border border-border rounded-lg px-3 py-2 text-xs font-semibold focus:outline-hidden text-foreground"
                  />

                  <div className="flex items-center justify-end gap-2.5">
                    <button
                      onClick={() => {
                        setShowCreateModal(false);
                        setError(null);
                        setNewKBName("");
                      }}
                      disabled={isSubmitting}
                      className="px-3.5 py-2 border border-border hover:bg-accent rounded-lg text-xs font-bold text-muted-foreground"
                    >
                      Cancel
                    </button>
                    <button
                      onClick={handleCreateKB}
                      disabled={!newKBName.trim() || isSubmitting}
                      className="px-3.5 py-2 bg-primary text-primary-foreground disabled:opacity-40 rounded-lg text-xs font-bold hover:bg-primary/95 transition-all flex items-center gap-1.5"
                    >
                      {isSubmitting ? (
                        <>
                          <Loader2 className="h-3 w-3 animate-spin" />
                          <span>Creating...</span>
                        </>
                      ) : (
                        <span>Create</span>
                      )}
                    </button>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
