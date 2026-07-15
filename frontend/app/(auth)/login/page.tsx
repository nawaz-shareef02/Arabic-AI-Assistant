"use client";

import React from "react";
import AuthCard from "@/components/auth/AuthCard";
import AuthLogo from "@/components/auth/AuthLogo";
import LoginForm from "@/components/auth/LoginForm";

export default function LoginPage() {
  return (
    <AuthCard className="flex flex-col gap-6">
      <AuthLogo size="md" />
      <LoginForm />
    </AuthCard>
  );
}
