"use client";

import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { NAVIGATION } from "@/lib/navigation";
import { cn } from "@/lib/utils";

export default function SidebarMenu() {
  const pathname = usePathname();

  return (
    <nav className="flex-1 space-y-1 px-3 py-4 overflow-y-auto">
      {NAVIGATION.map((item) => {
        const Icon = item.icon;
        const isActive = pathname === item.href || (item.href !== "/" && pathname?.startsWith(item.href));

        return (
          <Link
            key={item.title}
            href={item.href}
            className={cn(
              "flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all duration-200 group relative",
              isActive
                ? "bg-primary text-primary-foreground shadow-sm shadow-primary/10"
                : "text-muted-foreground hover:bg-accent hover:text-accent-foreground"
            )}
          >
            <Icon
              className={cn(
                "h-4 w-4 shrink-0 transition-transform duration-200 group-hover:scale-105",
                isActive ? "text-primary-foreground" : "text-muted-foreground group-hover:text-foreground"
              )}
            />
            <span>{item.title}</span>
            {isActive && (
              <span className="absolute left-1 top-1/4 bottom-1/4 w-1 rounded-full bg-primary-foreground" />
            )}
          </Link>
        );
      })}
    </nav>
  );
}
