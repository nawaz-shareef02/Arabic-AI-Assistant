"use client";

import React from "react";
import SearchBar from "./SearchBar";
import ThemeToggle from "./ThemeToggle";
import LanguageSwitcher from "./LanguageSwitcher";
import NotificationBell from "./NotificationBell";
import UserMenu from "./UserMenu";

export default function TopNavbar() {
  return (
    <header className="h-16 border-b border-border bg-background px-6 flex items-center justify-between gap-4 shrink-0">
      {/* Search Bar / Command Palette trigger */}
      <SearchBar />

      {/* Right utilities: Theme, Language, Notifications, User Profile */}
      <div className="flex items-center gap-3">
        <LanguageSwitcher />
        <ThemeToggle />
        <NotificationBell />
        <div className="h-6 w-px bg-border/80 mx-1" />
        <UserMenu />
      </div>
    </header>
  );
}
