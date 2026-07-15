from app.services.embedding_service import EmbeddingService


service = EmbeddingService()

print("=" * 50)

print("Model Loaded :", service.is_loaded())

print("Embedding Dimension :", service.get_dimension())

vector = service.embed_text(
    "ArabIQ is an enterprise AI platform."
)

print("Vector Length :", len(vector))

batch = service.embed_batch(
    [
        "Artificial Intelligence",
        "Arabic NLP",
        "Enterprise Search",
    ]
)

print("Batch Size :", len(batch))

print("=" * 50)