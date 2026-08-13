"use client";

import React, { useState, useEffect } from "react";
import { AIPerformanceService, AIScorecard, AIMetrics, OptimizationRecommendation } from "@/services/ai_performance";
import { Cpu, Zap, Activity, CheckCircle, AlertTriangle, Play, RefreshCw, BarChart2, Layers, TrendingUp } from "lucide-react";

export default function AIPerformancePage() {
  const [scorecard, setScorecard] = useState<AIScorecard | null>(null);
  const [metrics, setMetrics] = useState<AIMetrics | null>(null);
  const [recommendations, setRecommendations] = useState<OptimizationRecommendation[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isBenchmarking, setIsBenchmarking] = useState(false);
  const [selectedProfile, setSelectedProfile] = useState("Standard");

  const loadData = async () => {
    setIsLoading(true);
    try {
      const [sc, met, recs] = await Promise.all([
        AIPerformanceService.getScorecard(),
        AIPerformanceService.getMetrics(),
        AIPerformanceService.getRecommendations(),
      ]);
      setScorecard(sc);
      setMetrics(met);
      setRecommendations(recs.items);
    } catch (e) {
      console.error("Failed to load AI performance data", e);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const handleRunBenchmark = async () => {
    setIsBenchmarking(true);
    try {
      await AIPerformanceService.triggerBenchmark(selectedProfile);
      await loadData();
    } catch (e) {
      console.error("Benchmark failed", e);
    } finally {
      setIsBenchmarking(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-white p-6 space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-800 pb-5">
        <div>
          <div className="flex items-center gap-2">
            <div className="h-9 w-9 rounded-xl bg-purple-500/10 border border-purple-500/20 flex items-center justify-center text-purple-400">
              <Cpu className="h-5 w-5" />
            </div>
            <h1 className="text-2xl font-bold tracking-tight">AI Performance & Optimization</h1>
          </div>
          <p className="text-sm text-slate-400 mt-1">
            Enterprise AI Quality Scorecard, RAG Stage Bottleneck Analysis, and Prioritized Optimization Engine.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <select
            value={selectedProfile}
            onChange={(e) => setSelectedProfile(e.target.value)}
            className="bg-slate-900 border border-slate-800 rounded-xl px-3 py-2 text-xs font-semibold text-slate-200"
          >
            <option value="Quick">Quick Profile</option>
            <option value="Standard">Standard Profile</option>
            <option value="Full Regression">Full Regression Profile</option>
            <option value="Production Validation">Production Validation</option>
          </select>

          <button
            onClick={handleRunBenchmark}
            disabled={isBenchmarking}
            className="inline-flex items-center gap-2 px-4 py-2 bg-purple-600 hover:bg-purple-500 text-white text-xs font-bold rounded-xl transition-all shadow-md shadow-purple-600/20 disabled:opacity-50"
          >
            <Play className={`h-3.5 w-3.5 ${isBenchmarking ? "animate-spin" : ""}`} />
            {isBenchmarking ? "Evaluating..." : "Run ML Benchmark"}
          </button>
        </div>
      </div>

      {/* Executive AI Scorecard Banner */}
      {scorecard && (
        <div className="bg-gradient-to-r from-purple-950/40 via-slate-900 to-slate-900 border border-purple-500/20 rounded-2xl p-6 shadow-xl backdrop-blur-md">
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-6">
            <div className="space-y-1">
              <span className="text-xs uppercase tracking-wider font-semibold text-purple-400">Executive AI Health Scorecard</span>
              <div className="flex items-baseline gap-3">
                <span className="text-4xl font-extrabold text-white">{scorecard.overall_ai_health}</span>
                <span className="text-sm font-semibold text-slate-400">/ 100</span>
                <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                  {scorecard.status}
                </span>
              </div>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 w-full md:w-auto">
              <div className="bg-slate-950/50 border border-slate-800 p-3 rounded-xl">
                <span className="text-[11px] text-slate-400 block">Retrieval Quality</span>
                <span className="text-lg font-bold text-white">{scorecard.retrieval_quality}%</span>
              </div>
              <div className="bg-slate-950/50 border border-slate-800 p-3 rounded-xl">
                <span className="text-[11px] text-slate-400 block">Response Quality</span>
                <span className="text-lg font-bold text-white">{scorecard.response_quality}%</span>
              </div>
              <div className="bg-slate-950/50 border border-slate-800 p-3 rounded-xl">
                <span className="text-[11px] text-slate-400 block">Knowledge Health</span>
                <span className="text-lg font-bold text-white">{scorecard.knowledge_health}%</span>
              </div>
              <div className="bg-slate-950/50 border border-slate-800 p-3 rounded-xl">
                <span className="text-[11px] text-slate-400 block">Latency Score</span>
                <span className="text-lg font-bold text-white">{scorecard.latency_score}%</span>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Retrieval Quality Gauges */}
      {metrics && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          <div className="bg-slate-900/60 border border-slate-800 p-4 rounded-xl backdrop-blur-md">
            <span className="text-xs text-slate-400 font-medium">Precision@5</span>
            <div className="text-2xl font-bold text-emerald-400 mt-1">{(metrics.precision_at_5 * 100).toFixed(1)}%</div>
          </div>
          <div className="bg-slate-900/60 border border-slate-800 p-4 rounded-xl backdrop-blur-md">
            <span className="text-xs text-slate-400 font-medium">Recall@5</span>
            <div className="text-2xl font-bold text-blue-400 mt-1">{(metrics.recall_at_5 * 100).toFixed(1)}%</div>
          </div>
          <div className="bg-slate-900/60 border border-slate-800 p-4 rounded-xl backdrop-blur-md">
            <span className="text-xs text-slate-400 font-medium">MRR (Mean Rank)</span>
            <div className="text-2xl font-bold text-purple-400 mt-1">{(metrics.mrr * 100).toFixed(1)}%</div>
          </div>
          <div className="bg-slate-900/60 border border-slate-800 p-4 rounded-xl backdrop-blur-md">
            <span className="text-xs text-slate-400 font-medium">NDCG@5</span>
            <div className="text-2xl font-bold text-cyan-400 mt-1">{(metrics.ndcg_at_5 * 100).toFixed(1)}%</div>
          </div>
          <div className="bg-slate-900/60 border border-slate-800 p-4 rounded-xl backdrop-blur-md col-span-2 md:col-span-1">
            <span className="text-xs text-slate-400 font-medium">Hit Rate</span>
            <div className="text-2xl font-bold text-amber-400 mt-1">{(metrics.hit_rate * 100).toFixed(1)}%</div>
          </div>
        </div>
      )}

      {/* RAG Bottleneck Analysis & Recommendations */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* RAG Bottleneck Card */}
        {metrics && (
          <div className="bg-slate-900/40 border border-slate-800 rounded-xl p-5 space-y-4">
            <div className="flex items-center gap-2 border-b border-slate-800 pb-3">
              <Zap className="h-4 w-4 text-amber-400" />
              <h2 className="text-sm font-semibold tracking-wide uppercase text-slate-300">RAG Bottleneck Analysis</h2>
            </div>
            <div className="space-y-3">
              <div className="bg-slate-950 border border-slate-800 p-3.5 rounded-xl space-y-1">
                <span className="text-xs text-slate-400">Primary Bottleneck Stage</span>
                <div className="text-base font-bold text-amber-400">
                  {metrics.bottleneck_analysis.bottleneck_stage} ({metrics.bottleneck_analysis.bottleneck_percentage}%)
                </div>
                <p className="text-xs text-slate-400 mt-1">{metrics.bottleneck_analysis.recommendation}</p>
              </div>
            </div>
          </div>
        )}

        {/* Prioritized Recommendations Cards */}
        <div className="lg:col-span-2 bg-slate-900/40 border border-slate-800 rounded-xl p-5 space-y-4">
          <div className="flex items-center justify-between border-b border-slate-800 pb-3">
            <div className="flex items-center gap-2">
              <TrendingUp className="h-4 w-4 text-purple-400" />
              <h2 className="text-sm font-semibold tracking-wide uppercase text-slate-300">Optimization Recommendations</h2>
            </div>
            <span className="text-xs text-slate-400">{recommendations.length} Active Tuning Candidates</span>
          </div>

          <div className="space-y-3">
            {recommendations.map((rec) => (
              <div key={rec.id} className="bg-slate-950 border border-slate-800/80 p-4 rounded-xl space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${
                      rec.priority === "HIGH" ? "bg-red-500/10 text-red-400 border border-red-500/20" : "bg-amber-500/10 text-amber-400 border border-amber-500/20"
                    }`}>
                      {rec.priority}
                    </span>
                    <h3 className="text-xs font-bold text-white">{rec.title}</h3>
                  </div>
                  <span className="text-[11px] font-mono text-purple-400">{rec.expected_impact}</span>
                </div>
                <p className="text-xs text-slate-400">{rec.justification}</p>
                <div className="flex items-center justify-between pt-1 text-[11px] text-slate-500">
                  <span>Current: {rec.current_metric}</span>
                  <span>Target: {rec.expected_metric}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
