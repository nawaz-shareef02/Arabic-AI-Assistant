"use client";

import { useEffect } from "react";
import { AlertCircle, RotateCcw } from "lucide-react";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="min-h-screen bg-background flex flex-col items-center justify-center p-6 text-center select-none animate-in fade-in duration-300">
      <div className="h-16 w-16 rounded-2xl bg-red-500/10 text-red-500 flex items-center justify-center font-bold text-2xl mb-6">
        <AlertCircle className="h-8 w-8" />
      </div>
      <h1 className="text-2xl font-bold tracking-tight text-foreground">500 - Internal Server Error</h1>
      <p className="text-xs text-muted-foreground max-w-sm mt-2.5 leading-relaxed">
        A network error or runtime exception occurred inside the active Ollama node/vector cluster.
      </p>
      <div className="mt-6">
        <button
          onClick={() => reset()}
          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-primary-foreground font-bold text-xs shadow-md hover:bg-primary/95 transition-all"
        >
          <RotateCcw className="h-4 w-4" />
          Retry Connection
        </button>
      </div>
    </div>
  );
}
