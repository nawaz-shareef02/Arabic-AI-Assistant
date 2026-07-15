"use client";

import React, { useState, useEffect } from "react";
import { AnalyticsService, AnalyticsData } from "@/services/analytics";
import { BarChart3, AlertCircle } from "lucide-react";
import { cn } from "@/lib/utils";

export default function AnalyticsPage() {
  const [timeRange, setTimeRange] = useState("7d");
  const [data, setData] = useState<AnalyticsData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function loadAnalytics() {
      try {
        const analyticsData = await AnalyticsService.getAnalytics();
        setData(analyticsData);
      } catch (err) {
        console.error("Failed to load analytics:", err);
      } finally {
        setLoading(false);
      }
    }
    loadAnalytics();
  }, [timeRange]);

  if (loading) {
    return (
      <div className="space-y-6 max-w-7xl mx-auto animate-pulse">
        {/* Header Skeleton */}
        <div className="flex justify-between items-center">
          <div className="space-y-2">
            <div className="h-8 w-48 bg-slate-200 dark:bg-zinc-800 rounded-md" />
            <div className="h-4 w-72 bg-slate-200 dark:bg-zinc-800 rounded-md" />
          </div>
          <div className="h-9 w-32 bg-slate-200 dark:bg-zinc-800 rounded-lg" />
        </div>

        {/* Stats Skeleton */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="h-28 rounded-xl border border-border bg-card p-5 space-y-3">
              <div className="h-4 w-28 bg-slate-200 dark:bg-zinc-800 rounded-md" />
              <div className="h-6 w-20 bg-slate-200 dark:bg-zinc-800 rounded-md" />
            </div>
          ))}
        </div>

        {/* Chart Area Skeleton */}
        <div className="h-64 rounded-xl border border-border bg-card w-full" />
      </div>
    );
  }

  const stats = [
    { label: "Total Questions Asked", value: "0 Inquiries", change: "—", color: "text-blue-500 bg-blue-500/10 border-blue-500/10" },
    { label: "Bilingual translation accuracy", value: "0.0% BLEU", change: "—", color: "text-emerald-500 bg-emerald-500/10 border-emerald-500/10" },
    { label: "Avg LLM Latency", value: "0.00 seconds", change: "—", color: "text-amber-500 bg-amber-500/10 border-amber-500/10" },
    { label: "Vector DB Footprint", value: "0 vectors", change: "—", color: "text-violet-500 bg-violet-500/10 border-violet-500/10" }
  ];

  return (
    <div className="space-y-6 max-w-7xl mx-auto animate-in fade-in duration-300">
      {/* Header section */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h1 className="text-xl font-bold text-foreground">Usage & Quality Analytics</h1>
          <p className="text-xs text-muted-foreground mt-1">
            Monitor questions volume, indexing storage rates, and bilingual LLM answer latencies.
          </p>
        </div>
        <select
          value={timeRange}
          onChange={(e) => setTimeRange(e.target.value)}
          disabled
          className="bg-card border border-border rounded-lg px-3 py-2 text-xs font-semibold focus:outline-hidden text-muted-foreground cursor-not-allowed opacity-70"
        >
          <option value="24h">Last 24 Hours</option>
          <option value="7d">Last 7 Days</option>
          <option value="30d">Last 30 Days</option>
        </select>
      </div>

      {/* Stats cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
        {stats.map((stat, idx) => (
          <div key={idx} className="rounded-xl border border-border bg-card p-5 shadow-xs flex flex-col justify-between opacity-80">
            <div className="flex items-center justify-between">
              <span className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider">{stat.label}</span>
              <div className={cn("h-8 w-8 rounded-lg flex items-center justify-center border", stat.color)}>
                <BarChart3 className="h-4 w-4" />
              </div>
            </div>
            <div className="mt-4">
              <p className="text-sm font-bold text-foreground truncate">{stat.value}</p>
              <div className="flex items-center gap-1 mt-1 text-[10px] text-muted-foreground font-semibold">
                <span>{stat.change}</span>
                <span>no AI history</span>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Central Empty State Area */}
      <div className="rounded-xl border border-border bg-card p-12 shadow-xs text-center flex flex-col items-center justify-center gap-4 min-h-[350px]">
        <div className="flex h-14 w-14 items-center justify-center rounded-full bg-slate-100 dark:bg-zinc-800 text-slate-400 dark:text-zinc-500">
          <BarChart3 className="h-7 w-7" />
        </div>
        
        <div className="space-y-1">
          <h3 className="text-sm font-bold text-foreground">No Analytics Available Yet</h3>
          <p className="text-xs text-muted-foreground max-w-sm leading-relaxed">
            Analytics will appear after AI usage. Document uploads and RAG conversations are required to monitor semantic retrieval stats.
          </p>
        </div>

        <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg border border-border bg-muted/40 text-[10px] font-bold text-muted-foreground mt-2 animate-pulse">
          <AlertCircle className="h-3.5 w-3.5" />
          Waiting for telemetry connection to FastAPI endpoint
        </div>
      </div>
    </div>
  );
}
