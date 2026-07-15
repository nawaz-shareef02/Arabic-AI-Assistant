"use client";

import React, { useState, useEffect } from "react";
import { ModelsService, ModelConfig } from "@/services/models";
import {
  Cpu,
  RefreshCw,
  Zap,
  Server,
  Activity,
  HelpCircle,
  AlertTriangle,
  Loader2
} from "lucide-react";
import { cn } from "@/lib/utils";

export default function ModelsPage() {
  const [models, setModels] = useState<ModelConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [checking, setChecking] = useState(false);

  async function loadModels() {
    try {
      const data = await ModelsService.getModels();
      setModels(data);
    } catch (err) {
      console.error("Failed to load models list:", err);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadModels();
  }, []);

  const handleRefetch = async () => {
    setChecking(true);
    // Simulate refetch connection delay
    await new Promise((resolve) => setTimeout(resolve, 1000));
    setChecking(false);
    loadModels();
  };

  if (loading) {
    return (
      <div className="space-y-6 max-w-7xl mx-auto animate-pulse">
        <div className="flex justify-between items-center">
          <div className="space-y-2">
            <div className="h-8 w-48 bg-slate-200 dark:bg-zinc-800 rounded-md" />
            <div className="h-4 w-72 bg-slate-200 dark:bg-zinc-800 rounded-md" />
          </div>
          <div className="h-9 w-40 bg-slate-200 dark:bg-zinc-800 rounded-lg" />
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {[1, 2].map((i) => (
            <div key={i} className="h-72 rounded-xl border border-border bg-card p-5" />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-7xl mx-auto animate-in fade-in duration-300">
      {/* Header section */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h1 className="text-xl font-bold text-foreground">AI Models Registry</h1>
          <p className="text-xs text-muted-foreground mt-1">
            Configure LLM connections. Only secure, locally integrated models appear active to satisfy data residency rules.
          </p>
        </div>
        <button
          onClick={handleRefetch}
          disabled={checking}
          className="flex items-center gap-1.5 px-4 py-2 rounded-lg border border-border bg-card text-xs font-semibold text-foreground hover:bg-accent transition-all shadow-xs cursor-pointer disabled:cursor-not-allowed disabled:opacity-60"
        >
          {checking ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <RefreshCw className="h-3.5 w-3.5" />
          )}
          <span>{checking ? "Checking..." : "Refetch Endpoint Health"}</span>
        </button>
      </div>

      {/* Grid of model cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {models.map((model) => {
          const isConnected = model.status === "Running";

          return (
            <div
              key={model.id}
              className="rounded-xl border p-5 shadow-xs flex flex-col justify-between h-72 relative overflow-hidden bg-muted/10 border-border/40 opacity-80 cursor-not-allowed select-none"
            >
              {/* Card Header */}
              <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-2.5">
                  <div className="h-8 w-8 rounded-lg flex items-center justify-center font-bold text-sm shrink-0 bg-muted text-muted-foreground">
                    <Cpu className="h-4 w-4" />
                  </div>
                  <div>
                    <h3 className="font-bold text-foreground text-sm">{model.name}</h3>
                    <p className="text-[10px] text-muted-foreground font-semibold mt-0.5">{model.provider}</p>
                  </div>
                </div>

                <div className="flex items-center gap-1.5">
                  <span className="h-1.5 w-1.5 rounded-full bg-amber-500 animate-pulse shrink-0" />
                  <span className="text-[10px] font-bold text-amber-500 uppercase tracking-wider">
                    {model.status}
                  </span>
                </div>
              </div>

              {/* Description Body */}
              <p className="text-xs text-muted-foreground leading-normal mt-4 flex-1">
                {model.description}
              </p>

              {/* Technical Specifications */}
              <div className="grid grid-cols-2 gap-2 border-t border-border/50 pt-3.5 mt-4 text-[10px] text-muted-foreground font-semibold">
                <div className="flex items-center gap-1.5">
                  <Zap className="h-3.5 w-3.5 text-muted-foreground/60 shrink-0" />
                  <span>Latency: <strong className="text-foreground">{model.latency}</strong></span>
                </div>
                <div className="flex items-center gap-1.5">
                  <Server className="h-3.5 w-3.5 text-muted-foreground/60 shrink-0" />
                  <span>RAM: <strong className="text-foreground">{model.memory}</strong></span>
                </div>
                <div className="flex items-center gap-1.5">
                  <Activity className="h-3.5 w-3.5 text-muted-foreground/60 shrink-0" />
                  <span>Health: <strong className="text-foreground">{model.health}</strong></span>
                </div>
                <div className="flex items-center gap-1.5">
                  <HelpCircle className="h-3.5 w-3.5 text-muted-foreground/60 shrink-0" />
                  <span>Build: <strong className="text-foreground">{model.version}</strong></span>
                </div>
              </div>

              {/* Offline disclaimer at the bottom */}
              <div className="flex items-center gap-1.5 pt-4 mt-3 border-t border-border/30 text-[10px] text-amber-500 font-bold justify-center">
                <AlertTriangle className="h-3.5 w-3.5" />
                <span>Ollama Connection Required</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
