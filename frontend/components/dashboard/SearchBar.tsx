"use client";

import React, { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { Search, Command, ArrowRight, Sun, Moon } from "lucide-react";
import { NAVIGATION } from "@/lib/navigation";
import { useTheme } from "next-themes";
import { cn } from "@/lib/utils";

export default function SearchBar() {
  const [isOpen, setIsOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const router = useRouter();
  const { theme, setTheme } = useTheme();
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.key === "k" || e.key === "K") && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setIsOpen((prev) => !prev);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  useEffect(() => {
    if (isOpen) {
      setTimeout(() => inputRef.current?.focus(), 50);
      setSelectedIndex(0);
    }
  }, [isOpen]);

  const commandItems = [
    ...NAVIGATION.map((item) => ({
      type: "nav",
      label: `Go to ${item.title}`,
      description: `Navigate to ${item.title.toLowerCase()} page`,
      icon: item.icon,
      action: () => router.push(item.href),
    })),
    {
      type: "action",
      label: "Toggle Dark Mode",
      description: "Switch application theme mode",
      icon: theme === "dark" ? Sun : Moon,
      action: () => setTheme(theme === "dark" ? "light" : "dark"),
    },
  ];

  const filteredItems = commandItems.filter(
    (item) =>
      item.label.toLowerCase().includes(searchQuery.toLowerCase()) ||
      item.description.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelectedIndex((prev) => (prev + 1) % filteredItems.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelectedIndex((prev) => (prev - 1 + filteredItems.length) % filteredItems.length);
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (filteredItems[selectedIndex]) {
        filteredItems[selectedIndex].action();
        setIsOpen(false);
      }
    } else if (e.key === "Escape") {
      setIsOpen(false);
    }
  };

  return (
    <>
      <button
        onClick={() => setIsOpen(true)}
        className="flex items-center gap-2 rounded-lg border border-border bg-muted/40 hover:bg-muted/80 px-3 py-1.5 text-xs text-muted-foreground w-64 transition-all duration-200 focus:outline-hidden"
      >
        <Search className="h-3.5 w-3.5" />
        <span className="text-left flex-1 font-medium">Search or ask a question...</span>
        <kbd className="pointer-events-none inline-flex h-5 select-none items-center gap-0.5 rounded border border-border bg-card px-1.5 font-mono text-[9px] font-bold text-muted-foreground opacity-100">
          <span className="text-[10px]">Ctrl</span>K
        </kbd>
      </button>

      {isOpen && (
        <div className="fixed inset-0 z-50 flex items-start justify-center pt-[15vh]">
          <div
            className="fixed inset-0 bg-background/80 backdrop-blur-xs transition-opacity"
            onClick={() => setIsOpen(false)}
          />

          <div className="relative w-full max-w-xl rounded-xl border border-border bg-popover text-popover-foreground shadow-2xl p-0 overflow-hidden animate-in fade-in zoom-in-95 duration-200 flex flex-col">
            <div className="flex items-center border-b border-border px-4 py-3">
              <Search className="h-4 w-4 text-muted-foreground mr-3" />
              <input
                ref={inputRef}
                type="text"
                placeholder="Type a command or search documents..."
                value={searchQuery}
                onChange={(e) => {
                  setSearchQuery(e.target.value);
                  setSelectedIndex(0);
                }}
                onKeyDown={handleKeyDown}
                className="w-full bg-transparent text-sm placeholder:text-muted-foreground focus:outline-hidden text-foreground font-medium"
              />
              <button
                onClick={() => setIsOpen(false)}
                className="text-[10px] text-muted-foreground border border-border bg-muted/50 rounded px-1.5 py-0.5 font-mono font-bold hover:bg-muted transition-colors"
              >
                ESC
              </button>
            </div>

            <div className="max-h-[300px] overflow-y-auto p-2 space-y-1">
              {filteredItems.length > 0 ? (
                filteredItems.map((item, index) => {
                  const Icon = item.icon;
                  const isHighlighted = index === selectedIndex;
                  return (
                    <button
                      key={item.label}
                      onClick={() => {
                        item.action();
                        setIsOpen(false);
                      }}
                      onMouseEnter={() => setSelectedIndex(index)}
                      className={cn(
                        "flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left transition-colors",
                        isHighlighted
                          ? "bg-primary text-primary-foreground"
                          : "hover:bg-accent hover:text-accent-foreground"
                      )}
                    >
                      <Icon className={cn("h-4 w-4 shrink-0", isHighlighted ? "text-primary-foreground" : "text-muted-foreground")} />
                      <div className="flex-1 min-w-0">
                        <p className={cn("text-xs font-semibold leading-none", isHighlighted ? "text-primary-foreground" : "text-foreground")}>
                          {item.label}
                        </p>
                        <p className={cn("text-[10px] mt-0.5 leading-none", isHighlighted ? "text-primary-foreground/80" : "text-muted-foreground")}>
                          {item.description}
                        </p>
                      </div>
                      {isHighlighted && <ArrowRight className="h-3 w-3 text-primary-foreground shrink-0 animate-pulse" />}
                    </button>
                  );
                })
              ) : (
                <div className="px-4 py-8 text-center text-xs text-muted-foreground">
                  No matching commands or search results found.
                </div>
              )}
            </div>

            <div className="flex items-center justify-between border-t border-border px-4 py-2 bg-muted/30 text-[10px] text-muted-foreground font-semibold">
              <div className="flex items-center gap-2">
                <span>Navigate: <kbd className="border border-border bg-card px-1 rounded">↑↓</kbd></span>
                <span>Select: <kbd className="border border-border bg-card px-1 rounded">Enter</kbd></span>
              </div>
              <div className="flex items-center gap-1">
                <Command className="h-3 w-3" />
                <span>ArabIQ Command Palette</span>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
