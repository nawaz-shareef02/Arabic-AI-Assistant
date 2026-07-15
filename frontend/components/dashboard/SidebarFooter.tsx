"use client";

import React from "react";
import { LogOut, User as UserIcon } from "lucide-react";
import { useAuth } from "@/context/AuthContext";

export default function SidebarFooter() {
  const { currentUser, logout } = useAuth();

  const handleLogout = () => {
    logout();
  };

  const userName = currentUser?.name || "Guest User";
  const userRole = currentUser ? (currentUser.jobTitle || currentUser.role) : "Not Signed In";
  const userAvatar = currentUser?.avatar;

  return (
    <div className="flex items-center justify-between gap-3 px-4 py-4 border-t border-border mt-auto bg-card">
      <div className="flex items-center gap-3 min-w-0">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary font-bold text-sm relative">
          {userAvatar ? (
            <img src={userAvatar} alt={userName} className="h-full w-full rounded-full object-cover" />
          ) : (
            <UserIcon className="h-4 w-4" />
          )}
          {/* Unverified indicator dot */}
          <span className="absolute -top-0.5 -right-0.5 h-2 w-2 rounded-full bg-amber-500 ring-2 ring-card" />
        </div>
        <div className="flex flex-col min-w-0">
          <span className="text-xs font-semibold text-foreground truncate leading-none">{userName}</span>
          <span className="text-[9px] text-muted-foreground truncate mt-1">{userRole}</span>
          <span className="text-[8px] font-bold text-amber-600 dark:text-amber-400 uppercase tracking-wide mt-0.5">Session not verified</span>
        </div>
      </div>


      <button
        onClick={handleLogout}
        className="flex h-8 w-8 items-center justify-center rounded-lg hover:bg-destructive/10 text-muted-foreground hover:text-destructive transition-colors shrink-0"
        title="Logout"
      >
        <LogOut className="h-4 w-4" />
      </button>
    </div>
  );
}
