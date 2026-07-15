"use client";

import React from "react";
import AuthCard from "@/components/auth/AuthCard";
import AuthLogo from "@/components/auth/AuthLogo";
import RegisterForm from "@/components/auth/RegisterForm";

export default function RegisterPage() {
  return (
    <AuthCard className="flex flex-col gap-5 md:max-w-xl">
      <AuthLogo size="sm" />
      <div className="text-center -mt-2">
        <h2 className="text-base font-bold text-foreground">Create your Enterprise Account</h2>
      </div>
      <RegisterForm />
    </AuthCard>
  );
}
