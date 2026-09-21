"use client";

import React, { Suspense } from "react";
import AuthCard from "@/components/auth/AuthCard";
import AuthLogo from "@/components/auth/AuthLogo";
import AcceptInvitationForm from "@/components/auth/AcceptInvitationForm";
import { Loader2 } from "lucide-react";

export default function AcceptInvitationPage() {
  return (
    <AuthCard className="flex flex-col gap-4">
      <AuthLogo size="sm" />
      <div className="text-center -mt-2">
        <h2 className="text-base font-bold text-foreground">Join Organization</h2>
      </div>
      <Suspense
        fallback={
          <div className="flex flex-col items-center justify-center py-10 space-y-3">
            <Loader2 className="h-8 w-8 animate-spin text-primary" />
            <p className="text-xs text-muted-foreground">Loading invitation...</p>
          </div>
        }
      >
        <AcceptInvitationForm />
      </Suspense>
    </AuthCard>
  );
}
