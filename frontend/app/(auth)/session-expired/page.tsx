"use client";

import React from "react";
import AuthCard from "@/components/auth/AuthCard";
import AuthLogo from "@/components/auth/AuthLogo";
import Link from "next/link";
import { AlertTriangle, LogIn } from "lucide-react";

export default function SessionExpiredPage() {
  return (
    <AuthCard className="flex flex-col gap-5 items-center text-center">
      <AuthLogo size="sm" />
      <div className="flex h-12 w-12 items-center justify-center rounded-full bg-amber-500/10 text-amber-500 my-2 animate-pulse">
        <AlertTriangle className="h-6 w-6" />
      </div>
      <div className="flex flex-col gap-2">
        <h2 className="text-base font-bold text-foreground">Session Expired</h2>
        <p className="text-xs text-muted-foreground leading-relaxed">
          Your session has expired due to inactivity or token expiration. Please sign in again to restore access.
        </p>
      </div>
      <Link
        href="/login"
        className="flex w-full items-center justify-center gap-2 h-10 rounded-lg bg-primary hover:bg-primary/95 text-primary-foreground font-semibold text-xs shadow-md hover:shadow-lg transition-all duration-200 mt-2 cursor-pointer"
      >
        <LogIn className="h-4 w-4" />
        <span>Return to Sign In</span>
      </Link>
    </AuthCard>
  );
}
