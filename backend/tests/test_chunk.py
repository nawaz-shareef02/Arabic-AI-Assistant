from app.services.chunk_service import ChunkService

sample_text = (
    "Artificial Intelligence is transforming enterprise software. "
    * 200
)

service = ChunkService()

chunks = service.split_text(sample_text)

print(f"Total Chunks : {len(chunks)}")

for chunk in chunks:
    print(
        f"""
Chunk {chunk["chunk_index"]}
Characters : {chunk["char_count"]}
Tokens : {chunk["estimated_tokens"]}
Start : {chunk["start_offset"]}
End : {chunk["end_offset"]}
"""
    )