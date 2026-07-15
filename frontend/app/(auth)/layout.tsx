"use client";

import React from "react";
import AuthBackground from "@/components/auth/AuthBackground";
import ThemeToggle from "@/components/dashboard/ThemeToggle";
import LanguageSwitcher from "@/components/dashboard/LanguageSwitcher";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="relative min-h-screen w-full flex flex-col items-center justify-center p-4 md:p-6 overflow-x-hidden">
      {/* Background gradients and grid pattern */}
      <AuthBackground />

      {/* Floating Controls (Theme Toggle and Language Switcher) */}
      <div className="absolute top-4 right-4 flex items-center gap-3 z-50">
        <LanguageSwitcher />
        <ThemeToggle />
      </div>

      {/* Children Content (Auth Cards) */}
      <div className="w-full flex justify-center py-8 z-10">
        {children}
      </div>

      {/* Simple Footer */}
      <div className="absolute bottom-4 text-center z-10">
        <p className="text-[10px] text-slate-500/70 dark:text-zinc-500/70 uppercase tracking-widest font-bold">
          © {new Date().getFullYear()} ArabIQ AI. All rights reserved.
        </p>
      </div>
    </div>
  );
}
