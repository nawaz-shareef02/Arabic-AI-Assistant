print("STEP 1")

from app.services.qdrant_service import QdrantService

print("STEP 2")

service = QdrantService()

print("STEP 3")

service.create_collection()

print("STEP 4")

print("Collection Ready")