"use client";

import React, { useState } from "react";
import { User, Settings, LogOut, ChevronDown } from "lucide-react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/context/AuthContext";

export default function UserMenu() {
  const [isOpen, setIsOpen] = useState(false);
  const router = useRouter();
  const { currentUser, logout } = useAuth();

  const user = {
    name: currentUser?.name || "Guest User",
    email: currentUser?.email || "Not Signed In",
  };

  return (
    <div className="relative">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-2 rounded-lg hover:bg-accent px-2 py-1.5 transition-colors focus:outline-hidden"
      >
        <div className="flex h-7 w-7 items-center justify-center rounded-full bg-primary/10 text-primary font-bold text-xs">
          <User className="h-3.5 w-3.5" />
        </div>
        <span className="text-xs font-semibold text-foreground hidden md:inline-block max-w-[120px] truncate">
          {user.name}
        </span>
        <ChevronDown className="h-3 w-3 text-muted-foreground hidden md:inline-block" />
      </button>

      {isOpen && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setIsOpen(false)} />
          <div className="absolute right-0 mt-1.5 z-20 w-48 rounded-lg border border-border bg-popover text-popover-foreground shadow-md p-1">
            <div className="px-2.5 py-2 border-b border-border/50 mb-1 flex flex-col gap-0.5">
              <p className="text-xs font-bold text-foreground truncate">{user.name}</p>
              <p className="text-[10px] text-muted-foreground truncate">{user.email}</p>
              
              <div className="mt-1 inline-flex items-center justify-center rounded px-1.5 py-0.5 text-[8px] font-bold uppercase tracking-wider bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-500/20">
                Session not verified
              </div>
            </div>

            <button
              onClick={() => {
                router.push("/settings");
                setIsOpen(false);
              }}
              className="flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-xs hover:bg-accent hover:text-accent-foreground transition-colors font-medium text-left"
            >
              <Settings className="h-3.5 w-3.5 text-muted-foreground" />
              <span>Settings</span>
            </button>

            <button
              onClick={() => {
                logout();
                setIsOpen(false);
              }}
              className="flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-xs hover:bg-destructive/10 hover:text-destructive text-muted-foreground transition-colors font-medium text-left"
            >
              <LogOut className="h-3.5 w-3.5" />
              <span>Log out</span>
            </button>
          </div>
        </>
      )}
    </div>
  );
}
