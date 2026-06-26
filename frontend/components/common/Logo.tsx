import { Bot } from "lucide-react";

export default function Logo() {
  return (
    <div className="flex items-center gap-3">
      <div className="rounded-xl bg-blue-600 p-2 text-white">
        <Bot className="h-6 w-6" />
      </div>

      <div>
        <h1 className="text-lg font-bold">
          Arabic-English AI Assistant
        </h1>

        <p className="text-sm text-gray-500">
          Enterprise Knowledge Assistant
        </p>
      </div>
    </div>
  );
}