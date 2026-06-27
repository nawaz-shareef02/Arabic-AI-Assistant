import Link from "next/link";
import { ArrowRight, Upload, CheckCircle } from "lucide-react";
import HeroPreview from "./HeroPreview";

export default function Hero() {
  return (
    <section className="relative overflow-hidden bg-gradient-to-br from-slate-50 via-white to-blue-50">
      <div className="mx-auto flex max-w-7xl flex-col items-center gap-16 px-6 py-24 lg:flex-row">

        {/* Left Section */}
        <div className="flex-1">

          <div className="mb-6 inline-flex items-center rounded-full border border-blue-200 bg-blue-100 px-4 py-2 text-sm font-medium text-blue-700">
            🚀 AI Powered Enterprise Platform
          </div>

          <h1 className="mb-8 text-5xl font-extrabold leading-tight lg:text-6xl">
            Enterprise AI Assistant

            <span className="mt-3 block bg-gradient-to-r from-blue-600 via-indigo-600 to-cyan-500 bg-clip-text text-transparent">
              for Saudi Organizations
            </span>
          </h1>

          <p className="mb-10 max-w-2xl text-lg leading-8 text-slate-600">
            Search, understand and interact with Arabic and English enterprise
            documents using Retrieval-Augmented Generation (RAG), semantic
            search and local AI models powered by Ollama.
          </p>

          {/* Buttons */}

          <div className="mb-10 flex flex-wrap gap-4">

            <Link
              href="/chat"
              className="flex items-center gap-2 rounded-xl bg-blue-600 px-7 py-4 font-semibold text-white shadow-lg transition hover:bg-blue-700"
            >
              Start Chat
              <ArrowRight className="h-5 w-5" />
            </Link>

            <Link
              href="/upload"
              className="flex items-center gap-2 rounded-xl border bg-white px-7 py-4 font-semibold shadow-sm transition hover:bg-slate-100"
            >
              <Upload className="h-5 w-5" />
              Upload Documents
            </Link>

          </div>

          {/* Features */}

          <div className="grid grid-cols-2 gap-4">
            {[
              "Arabic NLP",
              "English Translation",
              "Enterprise RAG",
              "Local Ollama AI",
            ].map((item) => (
              <div
                key={item}
                className="flex items-center gap-2 text-slate-700"
              >
                <CheckCircle className="h-5 w-5 text-green-500" />
                <span>{item}</span>
              </div>
            ))}
          </div>

        </div>

        {/* Right Section */}

        <div className="flex flex-1 justify-center">
          <HeroPreview />
        </div>

      </div>
    </section>
  );
}