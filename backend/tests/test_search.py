from app.services.search_service import SearchService
from app.database.session import SessionLocal

db = SessionLocal()

service = SearchService(db)

results = service.semantic_search(
    query="What is the history of Saudi Vision 2030?",
    knowledge_base_id=5,
)

print("=" * 60)

print("Retrieved:", len(results), "Chunks")

for index, item in enumerate(results, start=1):

    print(f"\nResult {index}")

    print("Score:", item.score)

    print(item.payload["text"][:300])

db.close()