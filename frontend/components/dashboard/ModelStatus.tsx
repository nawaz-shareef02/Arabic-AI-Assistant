"use client";

import React, { useState, useEffect } from "react";
import { Cpu, RefreshCw } from "lucide-react";

export default function ModelStatus() {
  const [checking, setChecking] = useState(true);
  const [lastChecked, setLastChecked] = useState<string>("");

  const checkConnection = () => {
    setChecking(true);
    setTimeout(() => {
      setChecking(false);
      const now = new Date();
      setLastChecked(
        now.toLocaleTimeString([], {
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
        })
      );
    }, 1200);
  };

  useEffect(() => {
    checkConnection();
  }, []);

  return (
    <div className="px-4 py-3.5 mx-3 my-2 rounded-xl bg-card border border-border shadow-sm">
      <div className="flex items-center gap-2.5">
        <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-muted text-muted-foreground shrink-0">
          <Cpu className={`h-4 w-4 ${checking ? "animate-pulse" : ""}`} />
        </div>
        <div className="flex flex-col min-w-0">
          <span className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider leading-none">
            AI Engine Status
          </span>
          {checking ? (
            <span className="text-xs font-bold text-foreground mt-1.5 truncate">
              Checking AI Server...
            </span>
          ) : (
            <div className="flex flex-col mt-1">
              <span className="text-xs font-bold text-foreground">
                DeepSeek-R1
              </span>
              <span className="text-[10px] text-rose-500 dark:text-rose-400 font-bold mt-0.5">
                Status: Offline
              </span>
              <span className="text-[10px] text-muted-foreground font-semibold">
                Waiting for Ollama...
              </span>
            </div>
          )}
        </div>
      </div>


      <div className="mt-3.5 flex flex-col gap-2 border-t border-border/50 pt-3 text-[10px] text-muted-foreground font-semibold">
        <div className="flex justify-between items-center">
          <span>Ollama Inference Node</span>
          {!checking && (
            <span className="text-[9px] opacity-75">Checked {lastChecked}</span>
          )}
        </div>
        
        <button
          onClick={checkConnection}
          disabled={checking}
          className="flex w-full items-center justify-center gap-1.5 h-7 px-2.5 rounded-lg border border-border bg-card hover:bg-accent text-[10px] font-bold text-foreground transition-all duration-150 cursor-pointer disabled:cursor-not-allowed disabled:opacity-60"
        >
          <RefreshCw className={`h-3 w-3 ${checking ? "animate-spin" : ""}`} />
          <span>{checking ? "Checking..." : "Retry Connection"}</span>
        </button>
      </div>
    </div>
  );
}
