"use client";

import React from "react";
import { APP_NAME } from "@/lib/constants";

interface AuthLogoProps {
  size?: "sm" | "md" | "lg";
}

export default function AuthLogo({ size = "md" }: AuthLogoProps) {
  const containerClasses = {
    sm: "gap-2",
    md: "gap-3",
    lg: "gap-4",
  };

  const iconClasses = {
    sm: "h-8 w-8 text-lg rounded-lg",
    md: "h-12 w-12 text-2xl rounded-xl",
    lg: "h-16 w-16 text-3xl rounded-2xl",
  };

  const titleClasses = {
    sm: "text-lg font-bold",
    md: "text-2xl font-extrabold tracking-tight",
    lg: "text-4xl font-extrabold tracking-tight",
  };

  const subtitleClasses = {
    sm: "text-[10px]",
    md: "text-xs",
    lg: "text-sm",
  };

  return (
    <div className={`flex flex-col items-center text-center ${containerClasses[size]}`}>
      <div 
        className={`flex items-center justify-center bg-primary text-primary-foreground font-bold shadow-xl shadow-primary/30 shrink-0 ${iconClasses[size]}`}
        style={{
          boxShadow: "0 10px 25px -5px rgba(var(--color-primary), 0.3)"
        }}
      >
        🤖
      </div>
      <div className="flex flex-col mt-2">
        <span className={`font-bold text-foreground dark:text-white leading-none ${titleClasses[size]}`}>
          {APP_NAME}
        </span>
        <span className={`text-muted-foreground mt-2 font-medium ${subtitleClasses[size]}`}>
          Enterprise AI Knowledge Platform
        </span>
      </div>
    </div>
  );
}
