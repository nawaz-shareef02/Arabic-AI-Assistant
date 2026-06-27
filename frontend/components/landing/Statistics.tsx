const stats = [
  {
    number: "2+",
    title: "Languages",
    description: "Arabic & English",
  },
  {
    number: "6+",
    title: "Document Types",
    description: "PDF, DOCX, TXT, PPTX...",
  },
  {
    number: "10+",
    title: "Enterprise Modules",
    description: "Chat, Upload, Search...",
  },
  {
    number: "5+",
    title: "AI Components",
    description: "RAG, LLM, Embeddings...",
  },
];

export default function Statistics() {
  return (
    <section className="bg-white py-20">
      <div className="mx-auto max-w-7xl px-6">

        <div className="mb-14 text-center">

          <h2 className="text-4xl font-bold">
            Platform Highlights
          </h2>

          <p className="mt-4 text-slate-600">
            Built for multilingual enterprise AI applications.
          </p>

        </div>

        <div className="grid gap-8 md:grid-cols-2 lg:grid-cols-4">

          {stats.map((stat) => (
            <div
              key={stat.title}
              className="rounded-3xl border border-slate-200 bg-slate-50 p-8 text-center shadow-sm transition hover:-translate-y-2 hover:shadow-xl"
            >
              <h3 className="mb-3 text-5xl font-extrabold text-blue-600">
                {stat.number}
              </h3>

              <p className="text-xl font-semibold">
                {stat.title}
              </p>

              <p className="mt-3 text-sm text-slate-500">
                {stat.description}
              </p>

            </div>
          ))}

        </div>

      </div>
    </section>
  );
}