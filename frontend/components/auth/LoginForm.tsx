"use client";

import React, { useState } from "react";
import Link from "next/link";
import { useAuth } from "@/context/AuthContext";
import PasswordInput from "./PasswordInput";
import RememberMe from "./RememberMe";
import SocialLogin from "./SocialLogin";
import { Input } from "@/components/ui/input";
import { Mail, Loader2, AlertCircle } from "lucide-react";

export default function LoginForm() {
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [rememberMe, setRememberMe] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<{ email?: string; password?: string }>({});
  const [isSubmitting, setIsSubmitting] = useState(false);

  const validate = () => {
    const errors: { email?: string; password?: string } = {};
    if (!email) {
      errors.email = "Email is required.";
    } else if (!/\S+@\S+\.\S+/.test(email)) {
      errors.email = "Please enter a valid email address.";
    }
    if (!password) {
      errors.password = "Password is required.";
    } else if (password.length < 6) {
      errors.password = "Password must be at least 6 characters.";
    }
    setFieldErrors(errors);
    return Object.keys(errors).length === 0;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!validate()) return;

    setIsSubmitting(true);
    try {
      await login({ email, password });
    } catch (err: any) {
      const errMsg = err.response?.data?.detail || err.message || "Failed to log in. Please check your credentials.";
      setError(errMsg);
      setIsSubmitting(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-5 w-full">
      {error && (
        <div className="flex items-center gap-2 p-3 rounded-lg border border-destructive/20 bg-destructive/10 text-destructive text-xs font-semibold">
          <AlertCircle className="h-4.5 w-4.5 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Email Input */}
      <div className="flex flex-col gap-1.5 w-full">
        <label className="text-xs font-bold text-muted-foreground uppercase tracking-wider block px-0.5">
          Email Address
        </label>
        <div className="relative flex items-center">
          <div className="absolute left-3 text-muted-foreground">
            <Mail className="h-4.5 w-4.5" />
          </div>
          <Input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="name@organization.com"
            className={`pl-10 h-10 border-slate-200 focus-visible:border-primary focus-visible:ring-primary/20 dark:border-zinc-800 ${
              fieldErrors.email ? "border-destructive focus-visible:border-destructive focus-visible:ring-destructive/20" : ""
            }`}
            autoComplete="email"
            required
          />
        </div>
        {fieldErrors.email && (
          <span className="text-[11px] text-destructive font-medium px-1 mt-0.5">
            {fieldErrors.email}
          </span>
        )}
      </div>

      {/* Password Input */}
      <PasswordInput
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        error={fieldErrors.password}
        placeholder="••••••••"
        autoComplete="current-password"
        required
      />

      {/* Remember Me & Forgot Password */}
      <div className="flex items-center justify-between mt-1 px-0.5">
        <RememberMe checked={rememberMe} onChange={setRememberMe} />
        <Link
          href="/forgot-password"
          className="text-xs font-bold text-primary hover:underline transition-all"
        >
          Forgot password?
        </Link>
      </div>

      {/* Submit Button */}
      <button
        type="submit"
        disabled={isSubmitting}
        className="flex w-full items-center justify-center gap-2 h-10 rounded-lg bg-primary hover:bg-primary/95 disabled:bg-primary/50 text-primary-foreground font-semibold text-xs shadow-md hover:shadow-lg transition-all duration-200 cursor-pointer disabled:cursor-not-allowed select-none"
      >
        {isSubmitting ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin" />
            <span>Signing in...</span>
          </>
        ) : (
          <span>Sign In</span>
        )}
      </button>

      {/* Social Logins */}
      <SocialLogin />

      {/* Register Link */}
      <p className="text-center text-xs font-semibold text-muted-foreground mt-4">
        Don&apos;t have an account?{" "}
        <Link
          href="/register"
          className="font-bold text-primary hover:underline transition-all"
        >
          Create an account
        </Link>
      </p>
    </form>
  );
}
