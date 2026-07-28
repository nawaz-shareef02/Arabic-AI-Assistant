"use client";

import React, { createContext, useContext, useState, useEffect } from "react";
import { KnowledgeBaseItem, KnowledgeBaseService } from "@/services/knowledge-base";
import { DocumentsService } from "@/services/documents";
import { useAuth } from "@/context/AuthContext";

interface KnowledgeBaseContextType {
  knowledgeBases: KnowledgeBaseItem[];
  selectedKbId: number | null;
  selectedKb: KnowledgeBaseItem | null;
  isLoading: boolean;
  error: string | null;
  setSelectedKbId: (id: number | null) => void;
  refreshKnowledgeBases: () => Promise<void>;
  createKnowledgeBase: (name: string) => Promise<KnowledgeBaseItem>;
  deleteKnowledgeBase: (uuid: string) => Promise<void>;
}

const KnowledgeBaseContext = createContext<KnowledgeBaseContextType | undefined>(undefined);

export function KnowledgeBaseProvider({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, isLoading: authLoading } = useAuth();
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBaseItem[]>([]);
  const [selectedKbId, setSelectedKbId] = useState<number | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refreshKnowledgeBases = async () => {
    setIsLoading(true);
    setError(null);
    try {
      // Fetch KBs and Documents to count docs per KB dynamically
      const [kbs, docs] = await Promise.all([
        KnowledgeBaseService.getKnowledgeBases(),
        DocumentsService.getDocuments()
      ]);

      const updatedKbs = kbs.map(kb => {
        const docsCount = docs.filter(doc => doc.kb === kb.uuid).length;
        return {
          ...kb,
          docsCount
        };
      });

      setKnowledgeBases(updatedKbs);
      
      // Auto-select first KB if none is selected
      if (updatedKbs.length > 0) {
        setSelectedKbId(prev => {
          if (prev !== null && updatedKbs.some(k => k.id === prev)) {
            return prev;
          }
          return updatedKbs[0].id;
        });
      } else {
        setSelectedKbId(null);
      }
    } catch (err: any) {
      console.error("Failed to load knowledge bases", err);
      setError(err.message || "Failed to load knowledge bases.");
    } finally {
      setIsLoading(false);
    }
  };

  // Only fetch knowledge bases after authentication is confirmed
  useEffect(() => {
    if (authLoading) return; // Wait for auth to finish verifying the session

    if (!isAuthenticated) {
      // User logged out or is not authenticated — clear KB state
      setKnowledgeBases([]);
      setSelectedKbId(null);
      setIsLoading(false);
      return;
    }

    refreshKnowledgeBases();
  }, [isAuthenticated, authLoading]);

  const createKB = async (name: string) => {
    setError(null);
    try {
      const newKb = await KnowledgeBaseService.createKnowledgeBase(name);
      setKnowledgeBases(prev => [...prev, newKb]);
      setSelectedKbId(newKb.id);
      return newKb;
    } catch (err: any) {
      setError(err.message || "Failed to create knowledge base.");
      throw err;
    }
  };

  const deleteKB = async (uuid: string) => {
    setError(null);
    try {
      await KnowledgeBaseService.deleteKnowledgeBase(uuid);
      setKnowledgeBases(prev => prev.filter(kb => kb.uuid !== uuid));
      // Re-evaluate selection
      setKnowledgeBases(prev => {
        if (prev.length > 0) {
          setSelectedKbId(curr => {
            if (curr !== null && prev.some(k => k.id === curr)) return curr;
            return prev[0].id;
          });
        } else {
          setSelectedKbId(null);
        }
        return prev;
      });
    } catch (err: any) {
      setError(err.message || "Failed to delete knowledge base.");
      throw err;
    }
  };

  const selectedKb = knowledgeBases.find(kb => kb.id === selectedKbId) || null;

  return (
    <KnowledgeBaseContext.Provider
      value={{
        knowledgeBases,
        selectedKbId,
        selectedKb,
        isLoading,
        error,
        setSelectedKbId,
        refreshKnowledgeBases,
        createKnowledgeBase: createKB,
        deleteKnowledgeBase: deleteKB
      }}
    >
      {children}
    </KnowledgeBaseContext.Provider>
  );
}

export function useKnowledgeBase() {
  const context = useContext(KnowledgeBaseContext);
  if (context === undefined) {
    throw new Error("useKnowledgeBase must be used within a KnowledgeBaseProvider");
  }
  return context;
}
