"use client";

import React from "react";
import AuthCard from "@/components/auth/AuthCard";
import AuthLogo from "@/components/auth/AuthLogo";
import ResetPasswordForm from "@/components/auth/ResetPasswordForm";

export default function ResetPasswordPage() {
  return (
    <AuthCard className="flex flex-col gap-5">
      <AuthLogo size="sm" />
      <div className="text-center -mt-2">
        <h2 className="text-base font-bold text-foreground">Set New Password</h2>
      </div>
      <ResetPasswordForm />
    </AuthCard>
  );
}
