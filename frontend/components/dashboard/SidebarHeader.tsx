"use client";

import React, { useState, useEffect } from "react";
import { APP_NAME } from "@/lib/constants";
import { ChevronDown, Database } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { KnowledgeBaseService, KnowledgeBaseItem } from "@/services/knowledge-base";

export default function SidebarHeader() {
  const { currentUser } = useAuth();
  const [kbs, setKbs] = useState<KnowledgeBaseItem[]>([]);
  const [isOpen, setIsOpen] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function loadKBs() {
      try {
        const data = await KnowledgeBaseService.getKnowledgeBases();
        setKbs(data);
      } catch (err) {
        console.error(err);
      } finally {
        setLoading(false);
      }
    }
    loadKBs();
  }, []);

  return (
    <div className="flex flex-col gap-4 px-4 py-5 border-b border-border">
      {/* Brand logo & title */}
      <div className="flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary text-primary-foreground font-bold text-xl shadow-lg shadow-primary/20 shrink-0">
          🤖
        </div>
        <div className="flex flex-col min-w-0">
          <span className="font-semibold text-base leading-none tracking-tight text-foreground truncate">{APP_NAME}</span>
          <span className="text-[11px] text-muted-foreground mt-1 truncate">
            {currentUser?.organization || "Enterprise AI Knowledge"}
          </span>
        </div>
      </div>

      {/* Knowledge Base Selector */}
      <div className="relative">
        <span className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider block mb-1.5 px-1">
          Knowledge Base
        </span>
        <button
          onClick={() => setIsOpen(!isOpen)}
          disabled={loading || kbs.length === 0}
          className="flex w-full items-center justify-between gap-2 rounded-lg border border-border bg-card hover:bg-accent hover:text-accent-foreground px-3 py-2 text-sm font-medium shadow-sm transition-all focus:outline-hidden cursor-not-allowed opacity-75"
        >
          <div className="flex items-center gap-2 text-muted-foreground truncate">
            <Database className="h-4 w-4 shrink-0 text-primary" />
            <span className="text-foreground text-xs font-semibold truncate">
              {loading ? "Loading..." : "No Knowledge Bases"}
            </span>
          </div>
          <ChevronDown className="h-3 w-3 opacity-50 shrink-0" />
        </button>
      </div>
    </div>
  );
}
