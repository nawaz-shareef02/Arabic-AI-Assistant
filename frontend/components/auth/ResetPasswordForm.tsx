"use client";

import React, { useState, useEffect } from "react";
import Link from "next/link";
import { useSearchParams, useRouter } from "next/navigation";
import { AuthService } from "@/services/auth";
import { Input } from "@/components/ui/input";
import { Lock, Loader2, AlertCircle, CheckCircle2, ArrowLeft } from "lucide-react";

export default function ResetPasswordForm() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const token = searchParams.get("token") || "";

  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (!token) {
      setError("Invalid or missing password reset link. Please request a new link.");
    }
  }, [token]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSuccess(false);

    if (!token) {
      setError("Invalid password reset token.");
      return;
    }

    if (!password) {
      setError("Password is required.");
      return;
    }

    if (password.length < 8) {
      setError("Password must be at least 8 characters long.");
      return;
    }

    if (password !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }

    setIsSubmitting(true);
    try {
      await AuthService.resetPassword(token, password);
      setSuccess(true);
    } catch (err: any) {
      const msg = err?.response?.data?.detail || err.message || "Failed to reset password. Token may be expired or invalid.";
      setError(msg);
    } finally {
      setIsSubmitting(false);
    }
  };

  if (success) {
    return (
      <div className="flex flex-col items-center text-center gap-5 w-full">
        <div className="flex h-12 w-12 items-center justify-center rounded-full bg-emerald-500/10 text-emerald-500">
          <CheckCircle2 className="h-6 w-6" />
        </div>
        <div className="flex flex-col gap-2">
          <h3 className="text-base font-bold text-foreground">Password Reset Successful</h3>
          <p className="text-xs text-muted-foreground leading-relaxed">
            Your password has been updated. All existing sessions have been signed out for security.
          </p>
        </div>
        <Link
          href="/login"
          className="flex w-full items-center justify-center gap-2 h-10 rounded-lg bg-primary hover:bg-primary/95 text-primary-foreground font-semibold text-xs shadow-md transition-all cursor-pointer mt-2"
        >
          <span>Sign In With New Password</span>
        </Link>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-5 w-full">
      <div className="flex flex-col gap-2 text-center mb-1">
        <p className="text-xs text-muted-foreground leading-relaxed">
          Please enter your new password below.
        </p>
      </div>

      {error && (
        <div className="flex items-center gap-2 p-3 rounded-lg border border-destructive/20 bg-destructive/10 text-destructive text-xs font-semibold">
          <AlertCircle className="h-4.5 w-4.5 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* New Password Input */}
      <div className="flex flex-col gap-1.5 w-full">
        <label className="text-xs font-bold text-muted-foreground uppercase tracking-wider block px-0.5">
          New Password
        </label>
        <div className="relative flex items-center">
          <div className="absolute left-3 text-muted-foreground">
            <Lock className="h-4.5 w-4.5" />
          </div>
          <Input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="••••••••"
            className="pl-10 h-10 border-slate-200 focus-visible:border-primary focus-visible:ring-primary/20 dark:border-zinc-800"
            required
            minLength={8}
          />
        </div>
      </div>

      {/* Confirm Password Input */}
      <div className="flex flex-col gap-1.5 w-full">
        <label className="text-xs font-bold text-muted-foreground uppercase tracking-wider block px-0.5">
          Confirm New Password
        </label>
        <div className="relative flex items-center">
          <div className="absolute left-3 text-muted-foreground">
            <Lock className="h-4.5 w-4.5" />
          </div>
          <Input
            type="password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            placeholder="••••••••"
            className="pl-10 h-10 border-slate-200 focus-visible:border-primary focus-visible:ring-primary/20 dark:border-zinc-800"
            required
            minLength={8}
          />
        </div>
      </div>

      {/* Submit Button */}
      <button
        type="submit"
        disabled={isSubmitting || !token}
        className="flex w-full items-center justify-center gap-2 h-10 rounded-lg bg-primary hover:bg-primary/95 disabled:bg-primary/50 text-primary-foreground font-semibold text-xs shadow-md hover:shadow-lg transition-all duration-200 cursor-pointer disabled:cursor-not-allowed select-none"
      >
        {isSubmitting ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin" />
            <span>Resetting password...</span>
          </>
        ) : (
          <span>Reset Password</span>
        )}
      </button>

      {/* Back to Login */}
      <Link
        href="/login"
        className="flex w-full items-center justify-center gap-2 h-10 rounded-lg border border-slate-200 dark:border-zinc-800 bg-card hover:bg-accent text-xs font-semibold text-foreground transition-all cursor-pointer mt-1"
      >
        <ArrowLeft className="h-4 w-4" />
        <span>Back to Login</span>
      </Link>
    </form>
  );
}
