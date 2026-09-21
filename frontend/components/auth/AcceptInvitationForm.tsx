"use client";

import React, { useState, useEffect } from "react";
import Link from "next/link";
import { useSearchParams, useRouter } from "next/navigation";
import { OrganizationService, VerifyInvitationResponse } from "@/services/organization";
import { useAuth } from "@/context/AuthContext";
import { Input } from "@/components/ui/input";
import {
  Lock,
  User as UserIcon,
  Building2,
  Shield,
  Loader2,
  AlertCircle,
  CheckCircle2,
  ArrowRight,
  Sparkles,
} from "lucide-react";

export default function AcceptInvitationForm() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const token = searchParams.get("token") || "";
  const { updateUser } = useAuth();

  const [loading, setLoading] = useState(true);
  const [invitation, setInvitation] = useState<VerifyInvitationResponse | null>(null);
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (!token) {
      setError("No invitation token found in link. Please verify your invitation email.");
      setLoading(false);
      return;
    }

    let isMounted = true;
    OrganizationService.verifyInvitation(token)
      .then((res) => {
        if (!isMounted) return;
        if (res.valid) {
          setInvitation(res);
        } else {
          setError(res.detail || "This invitation is invalid or has expired.");
        }
      })
      .catch((err) => {
        if (!isMounted) return;
        setError("Failed to verify invitation. Please check your network connection.");
      })
      .finally(() => {
        if (isMounted) setLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, [token]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!token) {
      setError("Invalid invitation token.");
      return;
    }

    if (!invitation?.user_exists) {
      if (!fullName.trim()) {
        setError("Full name is required.");
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
    } else {
      if (!password) {
        setError("Please enter your account password to accept this invitation.");
        return;
      }
    }

    setIsSubmitting(true);
    try {
      const res = await OrganizationService.acceptInvitation({
        token,
        full_name: fullName.trim() || undefined,
        password: password || undefined,
      });

      setSuccess(true);

      // User session established via server HttpOnly auth_token & csrf_token cookies
      if (res?.user) {
        updateUser({
          id: String(res.user.id),
          name: res.user.full_name || invitation?.email?.split("@")[0] || "User",
          email: res.user.email,
          role: invitation?.role_name || "member",
          organization: invitation?.organization_name || "Enterprise",
          preferredLanguage: "en",
          createdAt: new Date().toISOString(),
        });
      }

      setTimeout(() => {
        router.push("/dashboard");
      }, 2000);
    } catch (err: any) {
      const msg =
        err?.response?.data?.detail ||
        err?.message ||
        "Failed to accept invitation. The invitation may have expired or been revoked.";
      setError(msg);
    } finally {
      setIsSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-10 space-y-3">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
        <p className="text-xs text-muted-foreground font-medium">Verifying invitation link...</p>
      </div>
    );
  }

  if (success) {
    return (
      <div className="flex flex-col items-center text-center space-y-4 py-4">
        <div className="h-12 w-12 rounded-full bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-500">
          <CheckCircle2 className="h-6 w-6" />
        </div>
        <div className="space-y-1">
          <h3 className="text-base font-bold text-foreground">Welcome to {invitation?.organization_name}!</h3>
          <p className="text-xs text-muted-foreground">
            Your invitation has been accepted successfully. Redirecting you to your enterprise dashboard...
          </p>
        </div>
        <Link
          href="/dashboard"
          className="inline-flex items-center gap-2 h-9 px-4 rounded-lg bg-primary text-primary-foreground text-xs font-semibold hover:bg-primary/90 transition-colors"
        >
          <span>Go to Dashboard</span>
          <ArrowRight className="h-4 w-4" />
        </Link>
      </div>
    );
  }

  if (error && !invitation) {
    return (
      <div className="space-y-4 py-2">
        <div className="flex items-start gap-3 p-3.5 rounded-lg bg-destructive/10 border border-destructive/20 text-destructive text-xs">
          <AlertCircle className="h-4.5 w-4.5 shrink-0 mt-0.5" />
          <div className="space-y-1">
            <p className="font-semibold">Unable to Accept Invitation</p>
            <p className="text-xs opacity-90">{error}</p>
          </div>
        </div>

        <div className="pt-2 text-center">
          <Link
            href="/login"
            className="text-xs text-primary hover:underline font-semibold"
          >
            Return to Sign In
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {/* Invitation Context Banner */}
      <div className="rounded-xl border border-primary/20 bg-primary/5 p-4 space-y-2.5">
        <div className="flex items-center gap-2 text-primary font-bold text-xs">
          <Sparkles className="h-4 w-4" />
          <span>Organization Invitation</span>
        </div>
        <div className="space-y-1.5 text-xs text-muted-foreground">
          <div className="flex items-center gap-2 text-foreground font-semibold">
            <Building2 className="h-4 w-4 text-primary shrink-0" />
            <span className="truncate">{invitation?.organization_name}</span>
          </div>
          <div className="flex items-center gap-2">
            <Shield className="h-4 w-4 text-primary shrink-0" />
            <span>Role: <strong className="text-foreground">{invitation?.role_name}</strong></span>
          </div>
          <p className="text-[11px] pt-1 text-muted-foreground/80">
            Invited email: <strong className="text-foreground">{invitation?.email}</strong>
          </p>
        </div>
      </div>

      {error && (
        <div className="flex items-start gap-2 p-3 rounded-lg bg-destructive/10 border border-destructive/20 text-destructive text-xs font-semibold">
          <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-3.5">
        {!invitation?.user_exists ? (
          <>
            {/* New User: Full Name */}
            <div className="space-y-1">
              <label className="text-xs font-bold text-muted-foreground uppercase tracking-wider block">
                Full Name
              </label>
              <div className="relative flex items-center">
                <div className="absolute left-3 text-muted-foreground">
                  <UserIcon className="h-4 w-4" />
                </div>
                <Input
                  type="text"
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  placeholder="Your full name"
                  className="pl-9 h-10 border-slate-200 dark:border-zinc-800"
                  required
                />
              </div>
            </div>

            {/* New User: Password */}
            <div className="space-y-1">
              <label className="text-xs font-bold text-muted-foreground uppercase tracking-wider block">
                Create Password
              </label>
              <div className="relative flex items-center">
                <div className="absolute left-3 text-muted-foreground">
                  <Lock className="h-4 w-4" />
                </div>
                <Input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Min 8 characters"
                  className="pl-9 h-10 border-slate-200 dark:border-zinc-800"
                  required
                />
              </div>
            </div>

            {/* New User: Confirm Password */}
            <div className="space-y-1">
              <label className="text-xs font-bold text-muted-foreground uppercase tracking-wider block">
                Confirm Password
              </label>
              <div className="relative flex items-center">
                <div className="absolute left-3 text-muted-foreground">
                  <Lock className="h-4 w-4" />
                </div>
                <Input
                  type="password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  placeholder="Re-enter password"
                  className="pl-9 h-10 border-slate-200 dark:border-zinc-800"
                  required
                />
              </div>
            </div>
          </>
        ) : (
          /* Existing User: Password verification */
          <div className="space-y-1">
            <label className="text-xs font-bold text-muted-foreground uppercase tracking-wider block">
              Enter Account Password
            </label>
            <div className="relative flex items-center">
              <div className="absolute left-3 text-muted-foreground">
                <Lock className="h-4 w-4" />
              </div>
              <Input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Your account password"
                className="pl-9 h-10 border-slate-200 dark:border-zinc-800"
                required
              />
            </div>
            <p className="text-[11px] text-muted-foreground">
              An account already exists for {invitation?.email}. Enter your password to join this organization.
            </p>
          </div>
        )}

        <button
          type="submit"
          disabled={isSubmitting}
          className="w-full flex items-center justify-center gap-2 h-10 rounded-lg bg-primary text-primary-foreground text-xs font-bold shadow-md hover:bg-primary/90 transition-all duration-150 disabled:opacity-50 cursor-pointer mt-2"
        >
          {isSubmitting ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              <span>Accepting Invitation...</span>
            </>
          ) : (
            <>
              <span>Accept & Join Organization</span>
              <ArrowRight className="h-4 w-4" />
            </>
          )}
        </button>
      </form>
    </div>
  );
}
