"use client";

import React from "react";
import AuthCard from "@/components/auth/AuthCard";
import AuthLogo from "@/components/auth/AuthLogo";
import ForgotPasswordForm from "@/components/auth/ForgotPasswordForm";

export default function ForgotPasswordPage() {
  return (
    <AuthCard className="flex flex-col gap-5">
      <AuthLogo size="sm" />
      <div className="text-center -mt-2">
        <h2 className="text-base font-bold text-foreground">Reset Password</h2>
      </div>
      <ForgotPasswordForm />
    </AuthCard>
  );
}
