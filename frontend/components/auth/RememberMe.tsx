"use client";

import React from "react";

interface RememberMeProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
}

export default function RememberMe({ checked, onChange }: RememberMeProps) {
  return (
    <label className="flex items-center gap-2.5 cursor-pointer select-none group">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="h-4 w-4 rounded border-slate-300 dark:border-zinc-700 bg-card text-primary focus:ring-primary focus:ring-offset-2 dark:focus:ring-offset-zinc-900 focus:ring-2 accent-primary transition-all cursor-pointer"
      />
      <span className="text-xs font-semibold text-muted-foreground group-hover:text-foreground transition-colors">
        Remember me
      </span>
    </label>
  );
}
