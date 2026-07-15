"use client";

import React, { useState } from "react";
import { Bell, Inbox } from "lucide-react";
import { cn } from "@/lib/utils";

interface NotificationItem {
  id: string;
  title: string;
  time: string;
  unread: boolean;
}

export default function NotificationBell() {
  const [isOpen, setIsOpen] = useState(false);
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);

  const unreadCount = notifications.filter((n) => n.unread).length;

  const markAllAsRead = () => {
    setNotifications((prev) => prev.map((n) => ({ ...n, unread: false })));
  };

  return (
    <div className="relative">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex h-9 w-9 items-center justify-center rounded-lg border border-border bg-card hover:bg-accent hover:text-accent-foreground text-muted-foreground hover:text-foreground transition-all duration-200 shadow-sm relative focus:outline-hidden"
        title="Notifications"
      >
        <Bell className="h-4 w-4" />
        {unreadCount > 0 && (
          <span className="absolute top-1.5 right-1.5 h-2 w-2 rounded-full bg-primary ring-2 ring-background animate-pulse" />
        )}
      </button>

      {isOpen && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setIsOpen(false)} />
          <div className="absolute right-0 mt-1.5 z-20 w-80 rounded-xl border border-border bg-popover text-popover-foreground shadow-lg p-0 overflow-hidden">
            <div className="flex items-center justify-between border-b border-border px-4 py-2.5 bg-muted/20">
              <span className="text-xs font-bold text-foreground">Notifications</span>
              {unreadCount > 0 && (
                <button
                  onClick={markAllAsRead}
                  className="text-[10px] font-semibold text-primary hover:underline"
                >
                  Mark all read
                </button>
              )}
            </div>

            <div className="max-h-64 overflow-y-auto divide-y divide-border/50">
              {notifications.length > 0 ? (
                notifications.map((n) => (
                  <div
                    key={n.id}
                    className={cn(
                      "p-3 text-left transition-colors flex gap-2 items-start",
                      n.unread ? "bg-accent/30" : "hover:bg-accent/10"
                    )}
                  >
                    <div className={cn(
                      "h-1.5 w-1.5 rounded-full mt-1.5 shrink-0",
                      n.unread ? "bg-primary" : "bg-transparent"
                    )} />
                    <div className="flex-1 min-w-0">
                      <p className="text-xs font-medium text-foreground leading-normal">{n.title}</p>
                      <span className="text-[10px] text-muted-foreground mt-0.5 block">{n.time}</span>
                    </div>
                  </div>
                ))
              ) : (
                <div className="flex flex-col items-center justify-center py-10 text-muted-foreground gap-2">
                  <Inbox className="h-7 w-7 opacity-30" />
                  <span className="text-xs font-bold text-foreground">No Notifications</span>
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
