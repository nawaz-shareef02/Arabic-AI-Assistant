"use client";

import React, { useState } from "react";
import AuthCard from "@/components/auth/AuthCard";
import AuthLogo from "@/components/auth/AuthLogo";
import { useAuth } from "@/context/AuthContext";
import { useRouter } from "next/navigation";
import { 
  Building2, 
  Heart, 
  GraduationCap, 
  Scale, 
  Briefcase, 
  User, 
  ArrowRight,
  Loader2
} from "lucide-react";

interface WorkspaceOption {
  name: string;
  description: string;
  icon: React.ComponentType<{ className?: string }>;
  color: string;
  borderColor: string;
}

const WORKSPACES: WorkspaceOption[] = [
  {
    name: "Saudi Aramco Demo",
    description: "Enterprise oil & gas SOPs and AI engineering data.",
    icon: Building2,
    color: "bg-emerald-500/10 text-emerald-500 dark:text-emerald-400 border-emerald-500/20",
    borderColor: "hover:border-emerald-500/30",
  },
  {
    name: "Hospital Demo",
    description: "Medical standard operations and SOP policies.",
    icon: Heart,
    color: "bg-rose-500/10 text-rose-500 dark:text-rose-400 border-rose-500/20",
    borderColor: "hover:border-rose-500/30",
  },
  {
    name: "University Demo",
    description: "Academic guidelines and administrative docs.",
    icon: GraduationCap,
    color: "bg-violet-500/10 text-violet-500 dark:text-violet-400 border-violet-500/20",
    borderColor: "hover:border-violet-500/30",
  },
  {
    name: "Finance Demo",
    description: "Corporate financial reports and compliance data.",
    icon: Scale,
    color: "bg-amber-500/10 text-amber-500 dark:text-amber-400 border-amber-500/20",
    borderColor: "hover:border-amber-500/30",
  },
  {
    name: "Engineering Demo",
    description: "Technical schematics and source codes.",
    icon: Briefcase,
    color: "bg-blue-500/10 text-blue-500 dark:text-blue-400 border-blue-500/20",
    borderColor: "hover:border-blue-500/30",
  },
  {
    name: "Personal Workspace",
    description: "Individual private playground and chat space.",
    icon: User,
    color: "bg-slate-500/10 text-slate-500 dark:text-slate-400 border-slate-500/20",
    borderColor: "hover:border-slate-500/30",
  },
];

export default function SelectWorkspacePage() {
  const { currentUser, updateUser } = useAuth();
  const router = useRouter();
  const [loadingWorkspace, setLoadingWorkspace] = useState<string | null>(null);

  const handleSelect = async (workspaceName: string) => {
    if (!currentUser) return;
    setLoadingWorkspace(workspaceName);
    
    // Simulate brief latency for UX
    await new Promise((resolve) => setTimeout(resolve, 600));
    
    updateUser({
      ...currentUser,
      organization: workspaceName,
    });
    
    router.push("/dashboard");
  };

  return (
    <AuthCard className="flex flex-col gap-5 md:max-w-2xl w-full">
      <AuthLogo size="sm" />
      
      <div className="text-center -mt-2">
        <h2 className="text-base font-bold text-foreground">Select Workspace</h2>
        <p className="text-xs text-muted-foreground mt-1">
          Welcome back, <span className="font-bold text-foreground">{currentUser?.name}</span>. Please choose a tenant to continue.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 my-2">
        {WORKSPACES.map((workspace) => {
          const Icon = workspace.icon;
          const isSelected = currentUser?.organization === workspace.name;
          const isLoading = loadingWorkspace === workspace.name;

          return (
            <button
              key={workspace.name}
              onClick={() => handleSelect(workspace.name)}
              disabled={loadingWorkspace !== null}
              className={`flex items-start text-left gap-3.5 p-4 rounded-xl border border-slate-200/60 dark:border-zinc-800/80 bg-card hover:bg-accent/40 dark:hover:bg-accent/10 transition-all duration-300 group cursor-pointer disabled:cursor-not-allowed disabled:opacity-55 ${workspace.borderColor} ${
                isSelected ? "ring-2 ring-primary border-primary/50" : ""
              }`}
            >
              <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border ${workspace.color}`}>
                <Icon className="h-5 w-5" />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-1.5 justify-between">
                  <span className="text-xs font-bold text-foreground group-hover:text-primary transition-colors truncate">
                    {workspace.name}
                  </span>
                  {isLoading ? (
                    <Loader2 className="h-3 w-3 text-primary animate-spin shrink-0" />
                  ) : (
                    <ArrowRight className="h-3 w-3 opacity-0 group-hover:opacity-100 group-hover:translate-x-0.5 transition-all text-primary shrink-0" />
                  )}
                </div>
                <p className="text-[10px] text-muted-foreground mt-1 leading-relaxed">
                  {workspace.description}
                </p>
              </div>
            </button>
          );
        })}
      </div>

      <div className="text-center text-[10px] text-muted-foreground mt-1 font-semibold">
        Need access to another tenant? Contact your organization administrator.
      </div>
    </AuthCard>
  );
}
