"use client";

import React from "react";
import AuthCard from "@/components/auth/AuthCard";
import AuthLogo from "@/components/auth/AuthLogo";
import AuthBackground from "@/components/auth/AuthBackground";
import Link from "next/link";
import { ShieldAlert, ArrowLeft } from "lucide-react";

export default function AccessDeniedPage() {
  return (
    <div className="relative min-h-screen w-full flex flex-col items-center justify-center p-4 md:p-6 overflow-x-hidden">
      {/* Background gradients and pattern */}
      <AuthBackground />

      <AuthCard className="flex flex-col gap-5 items-center text-center">
        <AuthLogo size="sm" />
        <div className="flex h-12 w-12 items-center justify-center rounded-full bg-destructive/10 text-destructive my-2 animate-bounce" style={{ animationDuration: "3s" }}>
          <ShieldAlert className="h-6 w-6" />
        </div>
        <div className="flex flex-col gap-2">
          <h2 className="text-base font-bold text-foreground">Access Denied</h2>
          <p className="text-xs text-muted-foreground leading-relaxed">
            You do not have the required permissions to access this resource or page. 
            Role-Based Access Control (RBAC) is enforced. Please contact your system administrator if you believe this is an error.
          </p>
        </div>
        <Link
          href="/dashboard"
          className="flex w-full items-center justify-center gap-2 h-10 rounded-lg bg-primary hover:bg-primary/95 text-primary-foreground font-semibold text-xs shadow-md hover:shadow-lg transition-all duration-200 mt-2 cursor-pointer"
        >
          <ArrowLeft className="h-4 w-4" />
          <span>Return to Dashboard</span>
        </Link>
      </AuthCard>
    </div>
  );
}
