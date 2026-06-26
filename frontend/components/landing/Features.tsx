import {
  Languages,
  FileText,
  Brain,
  Database,
  Search,
  Globe,
} from "lucide-react";

const features = [
  {
    title: "Arabic NLP",
    icon: Languages,
  },
  {
    title: "Enterprise RAG",
    icon: Search,
  },
  {
    title: "PDF & DOCX",
    icon: FileText,
  },
  {
    title: "Ollama AI",
    icon: Brain,
  },
  {
    title: "Vector Database",
    icon: Database,
  },
  {
    title: "Multilingual",
    icon: Globe,
  },
];

export default function Features() {
  return (
    <section className="mx-auto grid max-w-6xl grid-cols-1 gap-6 px-6 pb-24 md:grid-cols-2 lg:grid-cols-3">
      {features.map((feature) => (
        <div
          key={feature.title}
          className="rounded-2xl border bg-white p-6 shadow-sm"
        >
          <feature.icon className="mb-4 h-10 w-10 text-blue-600" />

          <h2 className="mb-2 text-xl font-semibold">
            {feature.title}
          </h2>

          <p className="text-gray-600">
            Production-ready architecture for enterprise AI.
          </p>
        </div>
      ))}
    </section>
  );
}