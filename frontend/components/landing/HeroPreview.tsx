import { Bot, FileText, Globe, ShieldCheck } from "lucide-react";

export default function HeroPreview() {
  return (
    <div className="relative w-full max-w-lg rounded-3xl border border-slate-200 bg-white p-6 shadow-2xl">

      <div className="mb-5 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Bot className="h-6 w-6 text-blue-600" />
          <span className="font-semibold">
            AI Workspace Preview
          </span>
        </div>

        <span className="rounded-full bg-green-100 px-3 py-1 text-xs font-medium text-green-700">
          Live Demo
        </span>
      </div>

      <div className="space-y-4">

        <div className="rounded-xl bg-slate-100 p-4">
          <p className="text-xs text-slate-500 mb-2">
            User Question
          </p>

          <p className="font-medium">
            ما هي سياسة الإجازات السنوية؟
          </p>
        </div>

        <div className="rounded-xl bg-blue-50 p-4 border border-blue-100">

          <p className="mb-2 text-xs text-blue-700 font-semibold">
            🇸🇦 Arabic
          </p>

          <p className="text-sm">
            يحق للموظفين الحصول على 21 يومًا من الإجازة السنوية.
          </p>

          <hr className="my-4"/>

          <p className="mb-2 text-xs text-indigo-700 font-semibold">
            🇬🇧 English
          </p>

          <p className="text-sm">
            Employees are entitled to 21 days of annual leave.
          </p>

        </div>

        <div className="grid grid-cols-2 gap-3">

          <div className="rounded-xl border p-3">

            <FileText className="mb-2 h-5 w-5 text-blue-600"/>

            <p className="text-xs text-slate-500">
              Source
            </p>

            <p className="font-medium">
              HR_Policy.pdf
            </p>

          </div>

          <div className="rounded-xl border p-3">

            <ShieldCheck className="mb-2 h-5 w-5 text-green-600"/>

            <p className="text-xs text-slate-500">
              Confidence
            </p>

            <p className="font-bold text-green-600">
              96%
            </p>

          </div>

        </div>

        <div className="flex items-center gap-2 rounded-xl bg-slate-50 p-3">

          <Globe className="h-5 w-5 text-indigo-600"/>

          <span className="text-sm">
            Arabic ↔ English Translation Enabled
          </span>

        </div>

      </div>

    </div>
  );
}