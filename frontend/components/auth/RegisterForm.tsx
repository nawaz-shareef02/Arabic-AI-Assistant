"use client";

import React, { useState } from "react";
import Link from "next/link";
import { useAuth } from "@/context/AuthContext";
import PasswordInput from "./PasswordInput";
import { Input } from "@/components/ui/input";
import { User, Mail, Building2, Briefcase, Globe, Loader2, AlertCircle } from "lucide-react";

const ORGANIZATIONS = [
  "Personal Workspace",
  "Saudi Aramco Demo",
  "Hospital Demo",
  "University Demo",
  "Engineering Demo",
  "Finance Demo",
];

export default function RegisterForm() {
  const { register } = useAuth();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [organization, setOrganization] = useState(ORGANIZATIONS[0]);
  const [jobTitle, setJobTitle] = useState("");
  const [preferredLanguage, setPreferredLanguage] = useState<"en" | "ar">("en");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [acceptTerms, setAcceptTerms] = useState(false);

  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [isSubmitting, setIsSubmitting] = useState(false);

  const validate = () => {
    const errors: Record<string, string> = {};

    if (!name.trim()) errors.name = "Full Name is required.";
    if (!email.trim()) {
      errors.email = "Email is required.";
    } else if (!/\S+@\S+\.\S+/.test(email)) {
      errors.email = "Please enter a valid email address.";
    }
    if (!password) {
      errors.password = "Password is required.";
    } else if (password.length < 8) {
      errors.password = "Password must be at least 8 characters.";
    } else if (!/[A-Z]/.test(password)) {
      errors.password = "Password must contain at least one uppercase letter.";
    } else if (!/[a-z]/.test(password)) {
      errors.password = "Password must contain at least one lowercase letter.";
    } else if (!/\d/.test(password)) {
      errors.password = "Password must contain at least one digit.";
    } else if (!/[!@#$%^&*(),.?":{}|<>]/.test(password)) {
      errors.password = "Password must contain at least one special character.";
    } else if (email && password.toLowerCase().includes(email.split("@")[0].toLowerCase())) {
      errors.password = "Password cannot contain parts of your email address.";
    } else if (name && name.split(/\s+/).some(part => part.length > 2 && password.toLowerCase().includes(part.toLowerCase()))) {
      errors.password = "Password cannot contain parts of your name.";
    }
    if (password !== confirmPassword) {
      errors.confirmPassword = "Passwords do not match.";
    }
    if (!acceptTerms) {
      errors.acceptTerms = "You must accept the terms & conditions.";
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
      await register({
        name,
        email,
        organization,
        jobTitle,
        preferredLanguage,
        password,
      });
    } catch (err: any) {
      const errMsg = err.response?.data?.detail || err.message || "Failed to create an account. Please try again.";
      setError(errMsg);
      setIsSubmitting(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4 w-full">
      {error && (
        <div className="flex items-center gap-2 p-3 rounded-lg border border-destructive/20 bg-destructive/10 text-destructive text-xs font-semibold">
          <AlertCircle className="h-4.5 w-4.5 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Full Name Input */}
      <div className="flex flex-col gap-1.5 w-full">
        <label className="text-xs font-bold text-muted-foreground uppercase tracking-wider block px-0.5">
          Full Name
        </label>
        <div className="relative flex items-center">
          <div className="absolute left-3 text-muted-foreground">
            <User className="h-4.5 w-4.5" />
          </div>
          <Input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="John Doe"
            className={`pl-10 h-10 border-slate-200 focus-visible:border-primary focus-visible:ring-primary/20 dark:border-zinc-800 ${
              fieldErrors.name ? "border-destructive focus-visible:border-destructive focus-visible:ring-destructive/20" : ""
            }`}
            required
          />
        </div>
        {fieldErrors.name && (
          <span className="text-[11px] text-destructive font-medium px-1 mt-0.5">
            {fieldErrors.name}
          </span>
        )}
      </div>

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
            required
          />
        </div>
        {fieldErrors.email && (
          <span className="text-[11px] text-destructive font-medium px-1 mt-0.5">
            {fieldErrors.email}
          </span>
        )}
      </div>

      {/* Organization Select & Job Title Row */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Organization Name */}
        <div className="flex flex-col gap-1.5 w-full">
          <label className="text-xs font-bold text-muted-foreground uppercase tracking-wider block px-0.5">
            Organization
          </label>
          <div className="relative flex items-center">
            <div className="absolute left-3 text-muted-foreground">
              <Building2 className="h-4.5 w-4.5" />
            </div>
            <select
              value={organization}
              onChange={(e) => setOrganization(e.target.value)}
              className="h-10 w-full rounded-lg border border-slate-200 bg-transparent pl-10 pr-3 py-1 text-sm transition-colors outline-none focus:border-primary focus:ring-3 focus:ring-primary/20 dark:border-zinc-800 dark:bg-zinc-950/20 text-foreground dark:text-white"
            >
              {ORGANIZATIONS.map((org) => (
                <option key={org} value={org} className="dark:bg-zinc-900 dark:text-white text-slate-800">
                  {org}
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Job Title */}
        <div className="flex flex-col gap-1.5 w-full">
          <label className="text-xs font-bold text-muted-foreground uppercase tracking-wider block px-0.5">
            Job Title
          </label>
          <div className="relative flex items-center">
            <div className="absolute left-3 text-muted-foreground">
              <Briefcase className="h-4.5 w-4.5" />
            </div>
            <Input
              type="text"
              value={jobTitle}
              onChange={(e) => setJobTitle(e.target.value)}
              placeholder="e.g. AI Engineer"
              className="pl-10 h-10 border-slate-200 focus-visible:border-primary focus-visible:ring-primary/20 dark:border-zinc-800"
            />
          </div>
        </div>
      </div>

      {/* Preferred Language Select */}
      <div className="flex flex-col gap-1.5 w-full">
        <label className="text-xs font-bold text-muted-foreground uppercase tracking-wider block px-0.5">
          Preferred Language
        </label>
        <div className="relative flex items-center">
          <div className="absolute left-3 text-muted-foreground">
            <Globe className="h-4.5 w-4.5" />
          </div>
          <select
            value={preferredLanguage}
            onChange={(e) => setPreferredLanguage(e.target.value as "en" | "ar")}
            className="h-10 w-full rounded-lg border border-slate-200 bg-transparent pl-10 pr-3 py-1 text-sm transition-colors outline-none focus:border-primary focus:ring-3 focus:ring-primary/20 dark:border-zinc-800 dark:bg-zinc-950/20 text-foreground dark:text-white"
          >
            <option value="en" className="dark:bg-zinc-900 dark:text-white text-slate-800">English (English)</option>
            <option value="ar" className="dark:bg-zinc-900 dark:text-white text-slate-800">العربية (Arabic)</option>
          </select>
        </div>
      </div>

      {/* Password Fields */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <PasswordInput
          label="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          error={fieldErrors.password}
          placeholder="Min 8 chars"
          required
        />
        <PasswordInput
          label="Confirm Password"
          value={confirmPassword}
          onChange={(e) => setConfirmPassword(e.target.value)}
          error={fieldErrors.confirmPassword}
          placeholder="Repeat password"
          required
        />
      </div>

      {/* Accept Terms Checkbox */}
      <div className="flex flex-col gap-1 mt-2">
        <label className="flex items-start gap-2.5 cursor-pointer select-none group">
          <input
            type="checkbox"
            checked={acceptTerms}
            onChange={(e) => setAcceptTerms(e.target.checked)}
            className="h-4 w-4 rounded mt-0.5 border-slate-300 dark:border-zinc-700 bg-card text-primary focus:ring-primary focus:ring-offset-2 dark:focus:ring-offset-zinc-900 focus:ring-2 accent-primary transition-all cursor-pointer"
          />
          <span className="text-xs font-semibold text-muted-foreground group-hover:text-foreground transition-colors leading-tight">
            I accept the{" "}
            <Link href="/terms" className="text-primary hover:underline font-bold">
              Terms of Service
            </Link>{" "}
            and{" "}
            <Link href="/privacy" className="text-primary hover:underline font-bold">
              Privacy Policy
            </Link>
            .
          </span>
        </label>
        {fieldErrors.acceptTerms && (
          <span className="text-[11px] text-destructive font-medium px-1 mt-0.5">
            {fieldErrors.acceptTerms}
          </span>
        )}
      </div>

      {/* Submit Button */}
      <button
        type="submit"
        disabled={isSubmitting}
        className="flex w-full items-center justify-center gap-2 h-10 rounded-lg bg-primary hover:bg-primary/95 disabled:bg-primary/50 text-primary-foreground font-semibold text-xs shadow-md hover:shadow-lg transition-all duration-200 mt-2 cursor-pointer disabled:cursor-not-allowed select-none"
      >
        {isSubmitting ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin" />
            <span>Creating account...</span>
          </>
        ) : (
          <span>Create Account</span>
        )}
      </button>

      {/* Login Link */}
      <p className="text-center text-xs font-semibold text-muted-foreground mt-2">
        Already have an account?{" "}
        <Link
          href="/login"
          className="font-bold text-primary hover:underline transition-all"
        >
          Sign In
        </Link>
      </p>
    </form>
  );
}
