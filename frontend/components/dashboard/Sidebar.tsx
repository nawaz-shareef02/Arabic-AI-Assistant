"use client";

import React from "react";
import SidebarHeader from "./SidebarHeader";
import SidebarMenu from "./SidebarMenu";
import ModelStatus from "./ModelStatus";
import StorageCard from "./StorageCard";
import SidebarFooter from "./SidebarFooter";

export default function Sidebar() {
  return (
    <aside className="w-72 border-r border-border bg-sidebar text-sidebar-foreground flex flex-col h-full shrink-0">
      {/* Brand & Knowledge Base Selector */}
      <SidebarHeader />

      {/* Navigation menu list */}
      <SidebarMenu />

      {/* Stats and widgets area at the bottom before footer */}
      <div className="mt-auto flex flex-col gap-1 border-t border-border/40 pt-2 bg-sidebar/50">
        <ModelStatus />
        <StorageCard />
      </div>

      {/* User profile card & Logout */}
      <SidebarFooter />
    </aside>
  );
}
