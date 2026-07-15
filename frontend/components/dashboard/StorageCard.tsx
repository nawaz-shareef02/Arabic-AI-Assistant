"use client";

import React from "react";
import { HardDrive } from "lucide-react";

export default function StorageCard() {
  return (
    <div className="px-4 py-3.5 mx-3 my-2 rounded-xl bg-card border border-border shadow-sm">
      <div className="flex items-center gap-2 mb-2">
        <HardDrive className="h-4 w-4 text-primary shrink-0" />
        <span className="text-xs font-semibold text-foreground">Storage</span>
      </div>

      <div className="space-y-1.5">
        {/* Progress bar */}
        <div className="h-2 w-full bg-secondary rounded-full overflow-hidden">
          <div
            className="h-full bg-primary rounded-full transition-all duration-500 ease-out"
            style={{ width: "0%" }}
          />
        </div>

        {/* Legend */}
        <div className="flex flex-col text-[10px] text-muted-foreground font-semibold gap-0.5">
          <div className="flex justify-between">
            <span>0 MB Used</span>
            <span>0 Documents</span>
          </div>
          <span className="text-[9px] font-medium text-slate-500/80 dark:text-zinc-500/80 italic mt-0.5">No uploads yet</span>
        </div>
      </div>
    </div>
  );
}
