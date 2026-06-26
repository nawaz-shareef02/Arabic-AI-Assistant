export default function Hero() {
  return (
    <section className="mx-auto max-w-6xl px-6 py-24 text-center">
      <h1 className="mb-6 text-6xl font-extrabold">
        Enterprise AI Knowledge Assistant
      </h1>

      <p className="mx-auto mb-10 max-w-3xl text-xl text-gray-600">
        Search Arabic and English documents using AI,
        Retrieval-Augmented Generation (RAG),
        and multilingual semantic search.
      </p>

      <div className="flex justify-center gap-6">
        <button className="rounded-xl bg-blue-600 px-8 py-4 text-lg font-semibold text-white hover:bg-blue-700">
          Start Chat
        </button>

        <button className="rounded-xl border px-8 py-4 text-lg hover:bg-gray-100">
          Upload Documents
        </button>
      </div>
    </section>
  );
}