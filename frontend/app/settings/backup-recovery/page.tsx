"use client";

import React, { useState, useEffect } from "react";
import { BackupService, BackupRecord, DRReadiness } from "@/services/backup";
import { ShieldCheck, HardDrive, Database, RefreshCw, Play, FileText, CheckCircle2, AlertTriangle, Lock, Eye, Server, Clock } from "lucide-react";

export default function BackupRecoveryPage() {
  const [backups, setBackups] = useState<BackupRecord[]>([]);
  const [drReadiness, setDrReadiness] = useState<DRReadiness | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isCreating, setIsCreating] = useState(false);
  const [activeBackupType, setActiveBackupType] = useState("Full");
  const [activeComponent, setActiveComponent] = useState("All");
  const [dryRunResult, setDryRunResult] = useState<any | null>(null);
  const [activeRunbook, setActiveRunbook] = useState<any | null>(null);

  const loadData = async () => {
    setIsLoading(true);
    try {
      const [bkList, drData] = await Promise.all([
        BackupService.getBackups(),
        BackupService.getDRReadiness(),
      ]);
      setBackups(bkList);
      setDrReadiness(drData);
    } catch (e) {
      console.error("Failed to load backup data", e);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const handleCreateBackup = async () => {
    setIsCreating(true);
    try {
      await BackupService.createBackup(activeBackupType, activeComponent);
      await loadData();
    } catch (e) {
      console.error("Backup creation failed", e);
    } finally {
      setIsCreating(false);
    }
  };

  const handleDryRunRestore = async (backupUuid: string) => {
    try {
      const res = await BackupService.dryRunRestore(backupUuid, activeComponent);
      setDryRunResult(res);
    } catch (e) {
      console.error("Dry run restore failed", e);
    }
  };

  const handleLoadRunbook = async (scenario: string) => {
    try {
      const res = await BackupService.getRunbook(scenario);
      setActiveRunbook(res);
    } catch (e) {
      console.error("Runbook load failed", e);
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-white p-6 space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-800 pb-5">
        <div>
          <div className="flex items-center gap-2">
            <div className="h-9 w-9 rounded-xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400">
              <ShieldCheck className="h-5 w-5" />
            </div>
            <h1 className="text-2xl font-bold tracking-tight">Backup, Disaster Recovery & High Availability</h1>
          </div>
          <p className="text-sm text-slate-400 mt-1">
            Enterprise AES-256 Encrypted Backups, SHA-256 Integrity Verification, Component-Level Restore & HA Matrix.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <select
            value={activeBackupType}
            onChange={(e) => setActiveBackupType(e.target.value)}
            className="bg-slate-900 border border-slate-800 rounded-xl px-3 py-2 text-xs font-semibold text-slate-200"
          >
            <option value="Full">Full Backup</option>
            <option value="Incremental">Incremental</option>
            <option value="Differential">Differential</option>
            <option value="On-Demand">On-Demand</option>
          </select>

          <button
            onClick={handleCreateBackup}
            disabled={isCreating}
            className="inline-flex items-center gap-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold rounded-xl transition-all shadow-md shadow-emerald-600/20 disabled:opacity-50"
          >
            <HardDrive className={`h-3.5 w-3.5 ${isCreating ? "animate-spin" : ""}`} />
            {isCreating ? "Archiving..." : "Create Backup"}
          </button>
        </div>
      </div>

      {/* Recovery Readiness Score Banner */}
      {drReadiness && drReadiness.scorecard && (
        <div className="bg-gradient-to-r from-emerald-950/40 via-slate-900 to-slate-900 border border-emerald-500/20 rounded-2xl p-6 shadow-xl backdrop-blur-md">
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-6">
            <div className="space-y-1">
              <span className="text-xs uppercase tracking-wider font-semibold text-emerald-400">Overall DR Readiness Score</span>
              <div className="flex items-baseline gap-3">
                <span className="text-4xl font-extrabold text-white">{drReadiness.scorecard.overall_dr_readiness_score}%</span>
                <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                  {drReadiness.scorecard.status}
                </span>
              </div>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 w-full md:w-auto">
              <div className="bg-slate-950/50 border border-slate-800 p-3 rounded-xl">
                <span className="text-[11px] text-slate-400 block">Backup Integrity</span>
                <span className="text-lg font-bold text-white">{drReadiness.scorecard.backup_integrity}%</span>
              </div>
              <div className="bg-slate-950/50 border border-slate-800 p-3 rounded-xl">
                <span className="text-[11px] text-slate-400 block">Restore Validation</span>
                <span className="text-lg font-bold text-white">{drReadiness.scorecard.restore_validation}%</span>
              </div>
              <div className="bg-slate-950/50 border border-slate-800 p-3 rounded-xl">
                <span className="text-[11px] text-slate-400 block">Replication Ready</span>
                <span className="text-lg font-bold text-white">{drReadiness.scorecard.replication_ready}%</span>
              </div>
              <div className="bg-slate-950/50 border border-slate-800 p-3 rounded-xl">
                <span className="text-[11px] text-slate-400 block">Automation Ready</span>
                <span className="text-lg font-bold text-white">{drReadiness.scorecard.automation_ready}%</span>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* HA Matrix & Runbook Trigger Cards */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* HA Matrix */}
        {drReadiness && (
          <div className="bg-slate-900/40 border border-slate-800 rounded-xl p-5 space-y-4">
            <div className="flex items-center gap-2 border-b border-slate-800 pb-3">
              <Server className="h-4 w-4 text-emerald-400" />
              <h2 className="text-sm font-semibold tracking-wide uppercase text-slate-300">HA Readiness Matrix</h2>
            </div>
            <div className="space-y-3">
              {drReadiness.ha_matrix.map((item, idx) => (
                <div key={idx} className="bg-slate-950 border border-slate-800 p-3 rounded-xl space-y-1">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold text-white">{item.component}</span>
                    <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                      {item.status}
                    </span>
                  </div>
                  <p className="text-xs text-slate-400">{item.notes}</p>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Backup History Table */}
        <div className="lg:col-span-2 bg-slate-900/40 border border-slate-800 rounded-xl p-5 space-y-4">
          <div className="flex items-center justify-between border-b border-slate-800 pb-3">
            <div className="flex items-center gap-2">
              <Database className="h-4 w-4 text-blue-400" />
              <h2 className="text-sm font-semibold tracking-wide uppercase text-slate-300">Backup Archives & Manifests</h2>
            </div>
            <span className="text-xs text-slate-400">{backups.length} Archives</span>
          </div>

          <div className="space-y-3">
            {backups.map((bk) => (
              <div key={bk.uuid} className="bg-slate-950 border border-slate-800 p-4 rounded-xl space-y-2">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase bg-blue-500/10 text-blue-400 border border-blue-500/20">
                      {bk.backup_type}
                    </span>
                    <span className="text-xs font-mono text-white">{bk.uuid.substring(0, 18)}...</span>
                  </div>

                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => handleDryRunRestore(bk.uuid)}
                      className="px-2.5 py-1 bg-slate-800 hover:bg-slate-700 text-xs font-semibold rounded text-slate-200"
                    >
                      Dry Run Restore
                    </button>
                  </div>
                </div>

                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-[11px] text-slate-400 pt-1 border-t border-slate-900">
                  <span>Size: {(bk.size_bytes / 1024).toFixed(1)} KB</span>
                  <span>SHA-256: {bk.checksum_sha256.substring(0, 8)}...</span>
                  <span>AES-256: {bk.is_encrypted ? "Yes" : "No"}</span>
                  <span>RTO: {bk.rto_seconds}s</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
