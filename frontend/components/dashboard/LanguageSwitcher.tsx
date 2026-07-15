"use client";

import React, { useState } from "react";
import { Globe, Check } from "lucide-react";

export default function LanguageSwitcher() {
  const [lang, setLang] = useState<"en" | "ar">("en");
  const [isOpen, setIsOpen] = useState(false);

  const toggleLang = (target: "en" | "ar") => {
    setLang(target);
    setIsOpen(false);
    document.documentElement.dir = target === "ar" ? "rtl" : "ltr";
    document.documentElement.lang = target;
  };

  return (
    <div className="relative">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex h-9 items-center gap-1.5 rounded-lg border border-border bg-card hover:bg-accent hover:text-accent-foreground px-2.5 text-xs font-semibold text-muted-foreground hover:text-foreground transition-all duration-200 shadow-sm focus:outline-hidden"
        title="Switch Language"
      >
        <Globe className="h-3.5 w-3.5 shrink-0" />
        <span>{lang === "en" ? "English" : "العربية"}</span>
      </button>

      {isOpen && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setIsOpen(false)} />
          <div className="absolute right-0 mt-1.5 z-20 w-32 rounded-lg border border-border bg-popover text-popover-foreground shadow-md p-1">
            <button
              onClick={() => toggleLang("en")}
              className="flex w-full items-center justify-between gap-2 rounded-md px-2.5 py-1.5 text-xs hover:bg-accent hover:text-accent-foreground transition-colors font-medium text-left"
            >
              <span>English</span>
              {lang === "en" && <Check className="h-3.5 w-3.5 text-primary shrink-0" />}
            </button>
            <button
              onClick={() => toggleLang("ar")}
              className="flex w-full items-center justify-between gap-2 rounded-md px-2.5 py-1.5 text-xs hover:bg-accent hover:text-accent-foreground transition-colors font-semibold text-right"
            >
              <span className="w-full text-right">العربية</span>
              {lang === "ar" && <Check className="h-3.5 w-3.5 text-primary shrink-0" />}
            </button>
          </div>
        </>
      )}
    </div>
  );
}
