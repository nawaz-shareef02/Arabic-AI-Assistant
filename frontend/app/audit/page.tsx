"use client";

import React, { useState, useEffect } from "react";
import { AuditService, AuditItem } from "@/services/audit";
import { ShieldCheck, Download, Search, Filter, RefreshCw, FileText, Lock, Users, Database, MessageSquare } from "lucide-react";

const CATEGORIES = [
  "All",
  "Authentication",
  "Organization",
  "Workspace",
  "Knowledge Base",
  "Document",
  "Chat",
  "Analytics",
  "Administration",
  "System",
];

export default function AuditPage() {
  const [logs, setLogs] = useState<AuditItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [selectedCategory, setSelectedCategory] = useState("All");
  const [searchAction, setSearchAction] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isExporting, setIsExporting] = useState(false);

  const fetchLogs = async () => {
    setIsLoading(true);
    try {
      const categoryParam = selectedCategory === "All" ? undefined : selectedCategory;
      const res = await AuditService.getAuditLogs({
        category: categoryParam,
        action: searchAction || undefined,
        page,
        page_size: 50,
      });
      setLogs(res.items);
      setTotal(res.total);
    } catch (err) {
      console.error("Failed to load audit logs", err);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchLogs();
  }, [page, selectedCategory]);

  const handleExportCsv = async () => {
    setIsExporting(true);
    try {
      const categoryParam = selectedCategory === "All" ? undefined : selectedCategory;
      const blob = await AuditService.exportAuditCsv({ category: categoryParam, action: searchAction });
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `arabiq_audit_logs_${new Date().toISOString().slice(0, 10)}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
    } catch (err) {
      console.error("CSV Export failed", err);
    } finally {
      setIsExporting(false);
    }
  };

  const getCategoryIcon = (category: string) => {
    switch (category) {
      case "Authentication": return <Lock className="h-4 w-4 text-amber-400" />;
      case "Organization": return <Users className="h-4 w-4 text-blue-400" />;
      case "Document": return <FileText className="h-4 w-4 text-emerald-400" />;
      case "Knowledge Base": return <Database className="h-4 w-4 text-purple-400" />;
      case "Chat": return <MessageSquare className="h-4 w-4 text-cyan-400" />;
      default: return <ShieldCheck className="h-4 w-4 text-slate-400" />;
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-white p-6 space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-800 pb-5">
        <div>
          <div className="flex items-center gap-2">
            <div className="h-9 w-9 rounded-xl bg-primary/10 border border-primary/20 flex items-center justify-center text-primary">
              <ShieldCheck className="h-5 w-5" />
            </div>
            <h1 className="text-2xl font-bold tracking-tight">Enterprise Audit Trail</h1>
          </div>
          <p className="text-sm text-slate-400 mt-1">
            Immutable, append-only compliance logs tracking all security, administration, and system events.
          </p>
        </div>

        <button
          onClick={handleExportCsv}
          disabled={isExporting}
          className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-white text-sm font-semibold border border-slate-700 transition-all shadow-md disabled:opacity-50"
        >
          <Download className="h-4 w-4 text-emerald-400" />
          {isExporting ? "Exporting CSV..." : "Export CSV Report"}
        </button>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center justify-between gap-4 bg-slate-900/60 border border-slate-800 p-4 rounded-xl backdrop-blur-md">
        <div className="flex items-center gap-2 overflow-x-auto pb-1 max-w-full">
          <Filter className="h-4 w-4 text-slate-400 shrink-0" />
          {CATEGORIES.map((cat) => (
            <button
              key={cat}
              onClick={() => { setSelectedCategory(cat); setPage(1); }}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold whitespace-nowrap transition-all ${
                selectedCategory === cat
                  ? "bg-primary text-primary-foreground shadow-md shadow-primary/20"
                  : "bg-slate-800/80 text-slate-400 hover:text-white hover:bg-slate-800"
              }`}
            >
              {cat}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-2 w-full sm:w-auto">
          <div className="relative flex-1 sm:w-64">
            <Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
            <input
              type="text"
              placeholder="Search action..."
              value={searchAction}
              onChange={(e) => setSearchAction(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && fetchLogs()}
              className="w-full pl-9 pr-3 py-1.5 bg-slate-950 border border-slate-800 rounded-lg text-xs text-white placeholder-slate-500 focus:outline-none focus:border-primary"
            />
          </div>
          <button
            onClick={fetchLogs}
            className="p-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 transition-all"
            title="Refresh Audit Logs"
          >
            <RefreshCw className={`h-4 w-4 ${isLoading ? "animate-spin" : ""}`} />
          </button>
        </div>
      </div>

      {/* Timeline Table */}
      <div className="bg-slate-900/40 border border-slate-800 rounded-xl overflow-hidden shadow-xl">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs text-slate-300">
            <thead className="bg-slate-900 border-b border-slate-800 uppercase tracking-wider text-[11px] text-slate-400">
              <tr>
                <th className="py-3.5 px-4 font-semibold">Timestamp</th>
                <th className="py-3.5 px-4 font-semibold">Category</th>
                <th className="py-3.5 px-4 font-semibold">Action</th>
                <th className="py-3.5 px-4 font-semibold">User</th>
                <th className="py-3.5 px-4 font-semibold">Status</th>
                <th className="py-3.5 px-4 font-semibold">Client IP</th>
                <th className="py-3.5 px-4 font-semibold">Request ID</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60">
              {isLoading ? (
                <tr>
                  <td colSpan={7} className="py-12 text-center text-slate-500 font-medium">
                    Loading compliance audit trail...
                  </td>
                </tr>
              ) : logs.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-12 text-center text-slate-500 font-medium">
                    No audit records match the selected filter.
                  </td>
                </tr>
              ) : (
                logs.map((log) => (
                  <tr key={log.id} className="hover:bg-slate-800/40 transition-colors">
                    <td className="py-3 px-4 text-slate-400 font-mono text-[11px] whitespace-nowrap">
                      {log.timestamp ? new Date(log.timestamp).toLocaleString() : "N/A"}
                    </td>
                    <td className="py-3 px-4">
                      <div className="flex items-center gap-1.5">
                        {getCategoryIcon(log.category)}
                        <span className="font-medium text-slate-200">{log.category}</span>
                      </div>
                    </td>
                    <td className="py-3 px-4 font-semibold text-white">{log.action}</td>
                    <td className="py-3 px-4 text-slate-400">{log.user_email || "System"}</td>
                    <td className="py-3 px-4">
                      <span
                        className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider ${
                          log.status === "success"
                            ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                            : "bg-red-500/10 text-red-400 border border-red-500/20"
                        }`}
                      >
                        {log.status}
                      </span>
                    </td>
                    <td className="py-3 px-4 font-mono text-slate-400">{log.client_ip || "127.0.0.1"}</td>
                    <td className="py-3 px-4 font-mono text-[10px] text-slate-500 truncate max-w-[120px]">
                      {log.request_id || "N/A"}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Footer Pagination */}
        <div className="flex items-center justify-between px-4 py-3 bg-slate-900/80 border-t border-slate-800 text-xs text-slate-400">
          <span>Showing {logs.length} of {total} events</span>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page === 1}
              className="px-3 py-1 bg-slate-800 rounded text-slate-300 disabled:opacity-40"
            >
              Previous
            </button>
            <span className="font-semibold text-white">Page {page}</span>
            <button
              onClick={() => setPage((p) => p + 1)}
              disabled={logs.length < 50}
              className="px-3 py-1 bg-slate-800 rounded text-slate-300 disabled:opacity-40"
            >
              Next
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
