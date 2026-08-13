"use client";

import React from "react";
import Link from "next/link";
import { ShieldAlert, ArrowLeft, Lock } from "lucide-react";

export default function AccessDeniedPage() {
  return (
    <div className="min-h-screen w-full flex flex-col items-center justify-center bg-slate-950 text-white p-6">
      <div className="max-w-md w-full flex flex-col items-center text-center space-y-6 bg-slate-900/80 border border-slate-800 p-8 rounded-2xl shadow-2xl backdrop-blur-xl">
        <div className="h-20 w-20 rounded-full bg-red-500/10 border border-red-500/20 flex items-center justify-center text-red-400">
          <ShieldAlert className="h-10 w-10" />
        </div>

        <div className="space-y-2">
          <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-red-500/10 border border-red-500/20 text-xs font-semibold text-red-400">
            <Lock className="h-3 w-3" />
            403 FORBIDDEN
          </div>
          <h1 className="text-2xl font-bold tracking-tight">Access Denied</h1>
          <p className="text-sm text-slate-400">
            You do not have the required permissions to access this resource or perform this enterprise action.
          </p>
        </div>

        <div className="w-full pt-4 border-t border-slate-800/80 flex flex-col gap-3">
          <Link
            href="/dashboard"
            className="w-full py-2.5 px-4 bg-primary text-primary-foreground font-semibold rounded-xl flex items-center justify-center gap-2 hover:bg-primary/90 transition-all text-sm shadow-lg shadow-primary/20"
          >
            <ArrowLeft className="h-4 w-4" />
            Return to Dashboard
          </Link>
          <span className="text-[11px] text-slate-500">
            Need access? Contact your Organization Administrator to request role elevated permissions.
          </span>
        </div>
      </div>
    </div>
  );
}
