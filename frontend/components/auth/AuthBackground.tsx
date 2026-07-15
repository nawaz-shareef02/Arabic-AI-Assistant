"use client";

import React from "react";

export default function AuthBackground() {
  return (
    <div className="absolute inset-0 -z-10 overflow-hidden bg-slate-950">
      {/* Decorative Radial Gradients */}
      <div className="absolute -top-[40%] -left-[20%] h-[100%] w-[80%] rounded-full bg-[radial-gradient(ellipse_at_center,var(--color-violet-600),transparent_70%)] opacity-[0.18] blur-3xl" />
      <div className="absolute -bottom-[40%] -right-[20%] h-[100%] w-[80%] rounded-full bg-[radial-gradient(ellipse_at_center,var(--color-emerald-600),transparent_70%)] opacity-[0.12] blur-3xl" />
      
      {/* Grid Pattern */}
      <div 
        className="absolute inset-0 opacity-[0.2]" 
        style={{
          backgroundImage: `
            linear-gradient(to right, rgba(148, 163, 184, 0.08) 1px, transparent 1px),
            linear-gradient(to bottom, rgba(148, 163, 184, 0.08) 1px, transparent 1px)
          `,
          backgroundSize: "3rem 3rem"
        }}
      />

      {/* Floating Ambient Lights */}
      <div className="absolute top-[20%] left-[10%] h-48 w-48 rounded-full bg-blue-500/10 blur-3xl animate-pulse" />
      <div className="absolute bottom-[30%] right-[15%] h-64 w-64 rounded-full bg-teal-500/5 blur-3xl animate-pulse" style={{ animationDuration: "8s" }} />
    </div>
  );
}
