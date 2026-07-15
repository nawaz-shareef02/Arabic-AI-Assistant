"use client";

import React, { useState, useEffect, useRef } from "react";
import { DashboardService, DashboardStats } from "@/services/dashboard";
import { HealthService, HealthStatus } from "@/services/health";
import { 
  FileText, 
  HelpCircle, 
  Database, 
  HardDrive, 
  AlertTriangle, 
  ArrowUpRight,
  Server,
  Activity,
  UploadCloud
} from "lucide-react";
import Link from "next/link";
import { cn } from "@/lib/utils";

export default function DashboardPage() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const delayRef = useRef<number>(2500);

  useEffect(() => {
    async function loadData() {
      try {
        const statsData = await DashboardService.getStats();
        const healthData = await HealthService.checkHealth();
        setStats(statsData);
        setHealth(healthData);
      } catch (err) {
        console.error("Error loading dashboard data:", err);
      } finally {
        setLoading(false);
      }
    }
    loadData();
  }, []);

  // Polling dashboard statistics automatically when documents are processing using recursive setTimeout & backoff
  useEffect(() => {
    if (!stats) return;

    const hasActiveParsing = (stats.parsingDocs ?? 0) > 0 || (stats.uploadedDocs ?? 0) > 0;
    const hasActiveActivity = stats.recentActivity?.some(
      (activity) => ["Queued", "Parsing", "Chunking", "Uploaded"].includes(activity.status)
    );

    if (!hasActiveParsing && !hasActiveActivity) {
      delayRef.current = 2500;
      return;
    }

    let timer: NodeJS.Timeout;

    async function pollDashboard() {
      try {
        const statsData = await DashboardService.getStats();
        setStats(statsData);
        delayRef.current = Math.min(delayRef.current + 1500, 10000);
        timer = setTimeout(pollDashboard, delayRef.current);
      } catch (err) {
        console.error("Error polling dashboard stats:", err);
        delayRef.current = Math.min(delayRef.current + 2000, 10000);
        timer = setTimeout(pollDashboard, delayRef.current);
      }
    }

    timer = setTimeout(pollDashboard, delayRef.current);
    return () => clearTimeout(timer);
  }, [stats]);

  if (loading) {
    return (
      <div className="space-y-6 max-w-7xl mx-auto">
        {/* Header Skeleton */}
        <div className="space-y-2">
          <div className="h-8 w-48 bg-slate-200 dark:bg-zinc-800 rounded-md animate-pulse" />
          <div className="h-4 w-72 bg-slate-200 dark:bg-zinc-800 rounded-md animate-pulse" />
        </div>

        {/* Stats Cards Skeleton */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="h-28 rounded-xl border border-border bg-card p-5 animate-pulse space-y-3">
              <div className="flex justify-between items-center">
                <div className="h-4 w-24 bg-slate-200 dark:bg-zinc-800 rounded-md" />
                <div className="h-8 w-8 bg-slate-200 dark:bg-zinc-800 rounded-lg" />
              </div>
              <div className="h-7 w-12 bg-slate-200 dark:bg-zinc-800 rounded-md" />
            </div>
          ))}
        </div>

        {/* Panels Skeleton */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 h-80 rounded-xl border border-border bg-card animate-pulse" />
          <div className="h-80 rounded-xl border border-border bg-card animate-pulse" />
        </div>
      </div>
    );
  }

  const statCards = [
    {
      title: "Documents",
      value: stats?.documents ?? 0,
      icon: FileText,
      color: "text-blue-500 bg-blue-500/10 border-blue-500/10",
    },
    {
      title: "Questions Asked",
      value: stats?.questions ?? 0,
      icon: HelpCircle,
      color: "text-violet-500 bg-violet-500/10 border-violet-500/10",
    },
    {
      title: "Knowledge Bases",
      value: stats?.knowledgeBases ?? 0,
      icon: Database,
      color: "text-emerald-500 bg-emerald-500/10 border-emerald-500/10",
    },
    {
      title: "Storage Used",
      value: `${stats?.storageUsedMb ?? 0} MB`,
      icon: HardDrive,
      color: "text-amber-500 bg-amber-500/10 border-amber-500/10",
    },
  ];

  const systemServices = [
    { name: "API Server", key: "apiServer" },
    { name: "Ollama Node", key: "ollama" },
    { name: "Qdrant Vector DB", key: "qdrant" },
    { name: "PostgreSQL Database", key: "postgres" },
    { name: "Redis Cache Store", key: "redis" },
  ];

  return (
    <div className="space-y-6 max-w-7xl mx-auto animate-in fade-in duration-300">
      {/* Title */}
      <div>
        <h1 className="text-xl font-bold tracking-tight text-foreground">Dashboard</h1>
        <p className="text-xs text-muted-foreground mt-1">
          Welcome back to the ArabIQ administrative command center.
        </p>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
        {statCards.map((card) => {
          const Icon = card.icon;
          return (
            <div key={card.title} className="rounded-xl border border-border bg-card p-5 shadow-xs hover:border-primary/50 transition-all flex flex-col justify-between h-28 relative overflow-hidden group">
              <div className="flex items-center justify-between gap-3">
                <span className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider">{card.title}</span>
                <div className={`h-8 w-8 rounded-lg flex items-center justify-center border ${card.color}`}>
                  <Icon className="h-4 w-4" />
                </div>
              </div>
              <div className="flex items-baseline gap-1 mt-2">
                <span className="text-2xl font-bold text-foreground">{card.value}</span>
              </div>
            </div>
          );
        })}
      </div>

      {/* Document Pipeline Progress Bar */}
      <div className="rounded-xl border border-border bg-card p-5 shadow-xs">
        <h3 className="text-xs font-bold text-foreground uppercase tracking-wider mb-4">
          Document Ingestion & Processing Pipeline
        </h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="flex flex-col p-3 rounded-lg bg-muted/20 border border-border/40 text-center">
            <span className="text-[10px] font-bold text-muted-foreground uppercase">Uploaded</span>
            <span className="text-lg font-bold text-foreground mt-1">{stats?.uploadedDocs ?? 0}</span>
            <span className="text-[9px] text-muted-foreground mt-0.5">Pending Scan & Parsing</span>
          </div>
          
          <div className="flex flex-col p-3 rounded-lg bg-muted/20 border border-border/40 text-center">
            <span className="text-[10px] font-bold text-primary uppercase">Parsing</span>
            <span className="text-lg font-bold text-primary mt-1 flex items-center justify-center gap-1.5">
              {(stats?.parsingDocs ?? 0) > 0 && <span className="h-2 w-2 rounded-full bg-primary animate-pulse" />}
              {stats?.parsingDocs ?? 0}
            </span>
            <span className="text-[9px] text-muted-foreground mt-0.5">Actively Processing</span>
          </div>

          <div className="flex flex-col p-3 rounded-lg bg-muted/20 border border-border/40 text-center">
            <span className="text-[10px] font-bold text-emerald-500 uppercase">Parsed</span>
            <span className="text-lg font-bold text-emerald-500 mt-1">{stats?.parsedDocs ?? 0}</span>
            <span className="text-[9px] text-muted-foreground mt-0.5">Ready for RAG Pipeline</span>
          </div>

          <div className="flex flex-col p-3 rounded-lg bg-muted/20 border border-border/40 text-center">
            <span className="text-[10px] font-bold text-rose-500 uppercase">Failed</span>
            <span className="text-lg font-bold text-rose-500 mt-1">{stats?.failedDocs ?? 0}</span>
            <span className="text-[9px] text-muted-foreground mt-0.5">Errors / Reparse Required</span>
          </div>
        </div>
      </div>

      {/* Main Content Areas */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Side: Activity Panel */}
        <div className="lg:col-span-2 rounded-xl border border-border bg-card p-6 shadow-sm flex flex-col justify-between min-h-[320px]">
          <div>
            <div className="flex items-center justify-between border-b border-border/65 pb-3 mb-6">
              <h3 className="text-xs font-bold text-foreground uppercase tracking-wider">
                Activity Stream
              </h3>
              {stats?.recentActivity && stats.recentActivity.length > 0 && (
                <Link
                  href="/documents"
                  className="text-[10px] font-bold text-primary hover:underline flex items-center gap-1"
                >
                  Manage All Files
                  <ArrowUpRight className="h-3 w-3" />
                </Link>
              )}
            </div>
            
            {stats?.recentActivity && stats.recentActivity.length > 0 ? (
              <div className="space-y-4">
                {stats.recentActivity.map((activity) => (
                  <div key={activity.uuid} className="flex items-center justify-between border-b border-border/40 pb-3 last:border-0 last:pb-0">
                    <div className="flex items-center gap-3 min-w-0">
                      <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10 text-primary border border-primary/10 shrink-0">
                        <FileText className="h-4 w-4" />
                      </div>
                      <div className="flex flex-col min-w-0">
                        <span className="text-xs font-bold text-foreground truncate max-w-[200px] sm:max-w-xs">{activity.filename}</span>
                        <span className="text-[10px] text-muted-foreground">
                          KB: {activity.kb_name} • {new Date(activity.created_at).toLocaleDateString()}
                        </span>
                      </div>
                    </div>
                    
                    <div className="flex items-center gap-2 shrink-0">
                      <span className={`text-[9px] font-bold px-2.5 py-0.5 rounded-full uppercase tracking-wider ${
                        activity.status === "Ready" || activity.status === "completed" || activity.status === "Parsed"
                          ? "bg-emerald-500/10 text-emerald-500 border border-emerald-500/10" 
                          : activity.status === "Failed" || activity.status === "failed"
                          ? "bg-rose-500/10 text-rose-500 border border-rose-500/10"
                          : "bg-amber-500/10 text-amber-500 border border-amber-500/10 animate-pulse"
                      }`}>
                        {activity.status}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center text-center py-10 text-muted-foreground gap-3">
                <div className="flex h-12 w-12 items-center justify-center rounded-full bg-slate-100 dark:bg-zinc-800 text-slate-400 dark:text-zinc-500">
                  <UploadCloud className="h-6 w-6" />
                </div>
                <div className="space-y-1">
                  <h4 className="text-xs font-bold text-foreground">No Activity Yet</h4>
                  <p className="text-[11px] text-muted-foreground max-w-xs leading-relaxed">
                    Start by uploading your first document to index knowledge clusters and begin AI conversations.
                  </p>
                </div>
                <Link
                  href="/upload"
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-primary hover:bg-primary/95 text-primary-foreground text-[10px] font-bold shadow-sm transition-all mt-2 cursor-pointer"
                >
                  Upload Document
                  <ArrowUpRight className="h-3 w-3" />
                </Link>
              </div>
            )}
          </div>
        </div>

        {/* Right Side: Infrastructure Health Widget */}
        <div className="rounded-xl border border-border bg-card p-6 shadow-sm flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between border-b border-border/65 pb-3 mb-4">
              <h3 className="text-xs font-bold text-foreground uppercase tracking-wider">
                System Status
              </h3>
              {health?.apiServer === "online" ? (
                <div className="flex items-center gap-1 text-[10px] font-bold text-emerald-500 bg-emerald-500/10 border border-emerald-500/10 px-2 py-0.5 rounded-full">
                  <span className="h-2 w-2 rounded-full bg-emerald-500 shrink-0" />
                  <span>Systems Active</span>
                </div>
              ) : health?.apiServer === "offline" ? (
                <div className="flex items-center gap-1 text-[10px] font-bold text-rose-500 bg-rose-500/10 border border-rose-500/10 px-2 py-0.5 rounded-full animate-pulse">
                  <AlertTriangle className="h-3 w-3 shrink-0" />
                  <span>System Offline</span>
                </div>
              ) : (
                <div className="flex items-center gap-1 text-[10px] font-bold text-amber-500 bg-amber-500/10 border border-amber-500/10 px-2 py-0.5 rounded-full">
                  <AlertTriangle className="h-3 w-3 shrink-0" />
                  <span>Waiting for Backend</span>
                </div>
              )}
            </div>

            <p className="text-[10px] text-slate-500 dark:text-zinc-400 leading-normal mb-5">
              Infrastructure connections will automatically resolve once the FastAPI service endpoints are active.
            </p>

            <div className="space-y-3.5">
              {systemServices.map((service) => {
                const status = health ? health[service.key as keyof HealthStatus] : "waiting";

                return (
                  <div key={service.name} className="flex items-center justify-between text-xs border-b border-border/30 pb-2.5 last:border-b-0 last:pb-0">
                    <div className="flex items-center gap-2">
                      <Server className="h-3.5 w-3.5 text-muted-foreground" />
                      <span className="font-semibold text-foreground">{service.name}</span>
                    </div>

                    <div className="flex items-center gap-1.5 font-bold text-[10px]">
                      <span className={cn(
                        "h-1.5 w-1.5 rounded-full shrink-0",
                        status === "online" 
                          ? "bg-emerald-500" 
                          : status === "offline" 
                          ? "bg-rose-500" 
                          : "bg-amber-500 animate-pulse"
                      )} />
                      <span className={cn(
                        "uppercase tracking-wider",
                        status === "online" 
                          ? "text-emerald-500" 
                          : status === "offline" 
                          ? "text-rose-500" 
                          : "text-amber-500"
                      )}>
                        {status === "online" ? "Online" : status === "offline" ? "Offline" : "Waiting..."}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="mt-6 pt-4 border-t border-border/50 flex items-center justify-between text-[9px] text-muted-foreground font-semibold">
            <span className="flex items-center gap-1">
              <Activity className="h-3.5 w-3.5 text-muted-foreground/60" />
              Health Poll Endpoint: GET /api/health
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}