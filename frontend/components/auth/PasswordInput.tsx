"use client";

import React, { useState } from "react";
import { Eye, EyeOff, Lock } from "lucide-react";
import { Input } from "@/components/ui/input";

interface PasswordInputProps extends React.ComponentProps<typeof Input> {
  label?: string;
  error?: string;
}

export default function PasswordInput({ label = "Password", error, className, ...props }: PasswordInputProps) {
  const [showPassword, setShowPassword] = useState(false);

  const toggleVisibility = () => {
    setShowPassword((prev) => !prev);
  };

  return (
    <div className="flex flex-col gap-1.5 w-full">
      <div className="flex justify-between items-center px-0.5">
        <label className="text-xs font-bold text-muted-foreground uppercase tracking-wider block">
          {label}
        </label>
      </div>
      <div className="relative flex items-center">
        <div className="absolute left-3 text-muted-foreground">
          <Lock className="h-4.5 w-4.5" />
        </div>
        <Input
          type={showPassword ? "text" : "password"}
          className={`pl-10 pr-10 h-10 border-slate-200 focus-visible:border-primary focus-visible:ring-primary/20 dark:border-zinc-800 ${
            error ? "border-destructive focus-visible:border-destructive focus-visible:ring-destructive/20" : ""
          } ${className}`}
          {...props}
        />
        <button
          type="button"
          onClick={toggleVisibility}
          className="absolute right-3 flex items-center justify-center text-muted-foreground hover:text-foreground transition-colors focus:outline-hidden cursor-pointer"
          tabIndex={-1}
          aria-label={showPassword ? "Hide password" : "Show password"}
        >
          {showPassword ? <EyeOff className="h-4.5 w-4.5" /> : <Eye className="h-4.5 w-4.5" />}
        </button>
      </div>
      {error && (
        <span className="text-[11px] text-destructive font-medium px-1 mt-0.5">
          {error}
        </span>
      )}
    </div>
  );
}
