"use client";

import React, { useState, useEffect } from "react";
import { useAuth } from "@/context/AuthContext";
import { Input } from "@/components/ui/input";
import { User as UserIcon, Mail, Building2, Briefcase, Globe, Save, CheckCircle2, Shield } from "lucide-react";

const ORGANIZATIONS = [
  "Personal Workspace",
  "Saudi Aramco Demo",
  "Hospital Demo",
  "University Demo",
  "Engineering Demo",
  "Finance Demo",
];

const LANGUAGES = [
  { value: "en", label: "English" },
  { value: "ar", label: "العربية (Arabic)" },
];

export default function SettingsPage() {
  const { currentUser, updateUser } = useAuth();

  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [organization, setOrganization] = useState(ORGANIZATIONS[0]);
  const [jobTitle, setJobTitle] = useState("");
  const [preferredLanguage, setPreferredLanguage] = useState<"en" | "ar">("en");
  const [role, setRole] = useState("employee");

  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Synchronize state with current user
  useEffect(() => {
    if (currentUser) {
      setName(currentUser.name);
      setEmail(currentUser.email);
      setOrganization(currentUser.organization || ORGANIZATIONS[0]);
      setJobTitle(currentUser.jobTitle || "");
      setPreferredLanguage(currentUser.preferredLanguage || "en");
      setRole(currentUser.role || "employee");
    }
  }, [currentUser]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setSaved(false);
    setError(null);

    if (!name.trim()) {
      setError("Full name is required.");
      return;
    }

    if (currentUser) {
      const updatedUser = {
        ...currentUser,
        name,
        organization,
        jobTitle,
        preferredLanguage,
      };

      updateUser(updatedUser);
      setSaved(true);

      setTimeout(() => {
        setSaved(false);
      }, 3000);
    }
  };

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      {/* Page Title */}
      <div>
        <h1 className="text-xl font-bold tracking-tight text-foreground">Settings</h1>
        <p className="text-xs text-muted-foreground mt-1">
          Manage your account profile and workspace configuration.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {/* Left Side: Profile Card */}
        <div className="md:col-span-1 space-y-6">
          <div className="rounded-xl border border-border bg-card p-6 shadow-sm flex flex-col items-center text-center">
            <div className="flex h-20 w-20 items-center justify-center rounded-full bg-primary/10 text-primary font-bold text-2xl mb-4 shadow-inner">
              {name ? name.charAt(0).toUpperCase() : <UserIcon className="h-10 w-10" />}
            </div>
            <h2 className="text-sm font-bold text-foreground truncate max-w-full">{name || "Guest User"}</h2>
            <p className="text-xs text-muted-foreground truncate max-w-full mb-3">{email}</p>
            <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-wider bg-primary/15 text-primary">
              <Shield className="h-3.5 w-3.5" />
              <span>{role}</span>
            </div>
          </div>
        </div>

        {/* Right Side: Profile Editor */}
        <div className="md:col-span-2">
          <div className="rounded-xl border border-border bg-card p-6 shadow-sm">
            <h3 className="text-xs font-bold text-foreground border-b border-border pb-3 mb-5 uppercase tracking-wider">
              Profile Settings
            </h3>

            <form onSubmit={handleSubmit} className="space-y-4">
              {saved && (
                <div className="flex items-center gap-2 p-3 rounded-lg border border-emerald-500/20 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 text-xs font-semibold">
                  <CheckCircle2 className="h-4.5 w-4.5 shrink-0" />
                  <span>Your changes have been saved successfully.</span>
                </div>
              )}

              {error && (
                <div className="flex items-center gap-2 p-3 rounded-lg border border-destructive/20 bg-destructive/10 text-destructive text-xs font-semibold">
                  <span>{error}</span>
                </div>
              )}

              {/* Full Name */}
              <div className="flex flex-col gap-1.5 w-full">
                <label className="text-xs font-bold text-muted-foreground uppercase tracking-wider block px-0.5">
                  Full Name
                </label>
                <div className="relative flex items-center">
                  <div className="absolute left-3 text-muted-foreground">
                    <UserIcon className="h-4.5 w-4.5" />
                  </div>
                  <Input
                    type="text"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    className="pl-10 h-10 border-slate-200 focus-visible:border-primary focus-visible:ring-primary/20 dark:border-zinc-800"
                    placeholder="Full Name"
                    required
                  />
                </div>
              </div>

              {/* Email Address */}
              <div className="flex flex-col gap-1.5 w-full opacity-70">
                <label className="text-xs font-bold text-muted-foreground uppercase tracking-wider block px-0.5">
                  Email Address (Unchangeable)
                </label>
                <div className="relative flex items-center">
                  <div className="absolute left-3 text-muted-foreground">
                    <Mail className="h-4.5 w-4.5" />
                  </div>
                  <Input
                    type="email"
                    value={email}
                    disabled
                    className="pl-10 h-10 bg-slate-100 dark:bg-zinc-800/50 cursor-not-allowed border-slate-200 dark:border-zinc-800"
                  />
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {/* Organization */}
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
                      className="pl-10 h-10 border-slate-200 focus-visible:border-primary focus-visible:ring-primary/20 dark:border-zinc-800"
                      placeholder="e.g. AI Analyst"
                    />
                  </div>
                </div>
              </div>

              {/* Preferred Language */}
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
                    {LANGUAGES.map((lang) => (
                      <option key={lang.value} value={lang.value} className="dark:bg-zinc-900 dark:text-white text-slate-800">
                        {lang.label}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              {/* Save Button */}
              <div className="pt-2">
                <button
                  type="submit"
                  className="flex items-center justify-center gap-2 h-10 px-4 rounded-lg bg-primary hover:bg-primary/95 text-primary-foreground font-semibold text-xs shadow-md hover:shadow-lg transition-all duration-200 cursor-pointer"
                >
                  <Save className="h-4 w-4" />
                  <span>Save Changes</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      </div>
    </div>
  );
}