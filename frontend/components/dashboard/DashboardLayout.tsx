"use client";

import React from "react";
import Sidebar from "./Sidebar";
import TopNavbar from "./TopNavbar";

interface DashboardLayoutProps {
  children: React.ReactNode;
}

export default function DashboardLayout({ children }: DashboardLayoutProps) {
  return (
    <div className="flex h-screen w-screen overflow-hidden bg-background">
      {/* Navigation sidebar */}
      <Sidebar />

      {/* Main workspace container */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Top Navbar headers */}
        <TopNavbar />

        {/* Dynamic page contents scrolling area */}
        <main className="flex-1 overflow-y-auto bg-slate-50/50 dark:bg-zinc-950/20 p-6">
          {children}
        </main>
      </div>
    </div>
  );
}
