import {
  Upload,
  FileText,
 Scissors,
  Brain,
  Database,
  Bot,
  Languages,
  BookOpen,
} from "lucide-react";

const workflow = [
  {
    icon: Upload,
    title: "Upload",
    description: "PDF, DOCX, PPTX, TXT",
  },
  {
    icon: FileText,
    title: "Parse",
    description: "Extract document content",
  },
  {
    icon: Scissors,
    title: "Chunk",
    description: "Split into semantic chunks",
  },
  {
    icon: Brain,
    title: "Embeddings",
    description: "Multilingual vectors",
  },
  {
    icon: Database,
    title: "Qdrant",
    description: "Vector similarity search",
  },
  {
    icon: Bot,
    title: "LLM",
    description: "DeepSeek / ALLaM",
  },
  {
    icon: Languages,
    title: "Bilingual",
    description: "Arabic + English",
  },
  {
    icon: BookOpen,
    title: "Sources",
    description: "Citation & confidence",
  },
];

export default function Workflow() {
  return (
    <section className="bg-slate-50 py-24">
      <div className="mx-auto max-w-7xl px-6">
        <div className="mb-16 text-center">
          <h2 className="text-4xl font-bold">
            How the AI Platform Works
          </h2>

          <p className="mt-4 text-slate-600">
            End-to-end Retrieval-Augmented Generation (RAG) pipeline.
          </p>
        </div>

        <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-4">
          {workflow.map((step) => (
            <div
              key={step.title}
              className="rounded-3xl border bg-white p-6 shadow-sm transition hover:-translate-y-2 hover:shadow-xl"
            >
              <step.icon className="mb-5 h-12 w-12 text-blue-600" />

              <h3 className="text-xl font-bold">
                {step.title}
              </h3>

              <p className="mt-3 text-slate-500">
                {step.description}
              </p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}