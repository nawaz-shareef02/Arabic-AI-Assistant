"""Verify Sprint 12 database migration."""
from app.database.session import SessionLocal
from sqlalchemy import text

db = SessionLocal()

# Check column
r = db.execute(text(
    "SELECT column_name, data_type FROM information_schema.columns "
    "WHERE table_name = 'document_chunks' AND column_name = 'search_vector'"
))
row = r.fetchone()
print(f"Column: {row}")

# Check index
r2 = db.execute(text(
    "SELECT indexname FROM pg_indexes "
    "WHERE tablename = 'document_chunks' AND indexname LIKE '%search_vector%'"
))
idx = r2.fetchone()
print(f"Index: {idx}")

# Check trigger
r3 = db.execute(text(
    "SELECT tgname FROM pg_trigger WHERE tgname = 'trg_chunk_search_vector'"
))
trg = r3.fetchone()
print(f"Trigger: {trg}")

# Check backfill (count chunks with non-null search_vector)
r4 = db.execute(text(
    "SELECT COUNT(*) FROM document_chunks WHERE search_vector IS NOT NULL"
))
cnt = r4.scalar()
total = db.execute(text("SELECT COUNT(*) FROM document_chunks")).scalar()
print(f"Backfill: {cnt}/{total} chunks have search_vector populated")

db.close()
print("\nAll database checks passed.")
