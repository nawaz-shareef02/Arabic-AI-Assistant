"use client";

import React, { useState } from "react";
import Link from "next/link";
import { AuthService } from "@/services/auth";
import { Input } from "@/components/ui/input";
import { Mail, Loader2, AlertCircle, CheckCircle2, ArrowLeft } from "lucide-react";

export default function ForgotPasswordForm() {
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSuccess(false);

    if (!email) {
      setError("Email address is required.");
      return;
    } else if (!/\S+@\S+\.\S+/.test(email)) {
      setError("Please enter a valid email address.");
      return;
    }

    setIsSubmitting(true);
    try {
      await AuthService.forgotPassword(email);
      setSuccess(true);
    } catch (err: any) {
      setError(err.message || "Failed to process your request. Please try again.");
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
          <h3 className="text-base font-bold text-foreground">Check your email</h3>
          <p className="text-xs text-muted-foreground leading-relaxed">
            We have sent password reset instructions to <span className="font-semibold text-foreground">{email}</span>.
            Please check your inbox and spam folders.
          </p>
        </div>
        <Link
          href="/login"
          className="flex w-full items-center justify-center gap-2 h-10 rounded-lg border border-slate-200 dark:border-zinc-800 bg-card hover:bg-accent text-xs font-semibold text-foreground transition-all cursor-pointer mt-2"
        >
          <ArrowLeft className="h-4 w-4" />
          <span>Back to Login</span>
        </Link>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-5 w-full">
      <div className="flex flex-col gap-2 text-center mb-1">
        <p className="text-xs text-muted-foreground leading-relaxed">
          Enter your email address and we will send you a secure link to reset your password.
        </p>
      </div>

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
              error ? "border-destructive focus-visible:border-destructive focus-visible:ring-destructive/20" : ""
            }`}
            required
          />
        </div>
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
            <span>Sending link...</span>
          </>
        ) : (
          <span>Send Reset Link</span>
        )}
      </button>

      {/* Back to Login Link */}
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
