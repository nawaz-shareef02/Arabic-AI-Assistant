from app.database.session import SessionLocal
from app.services.rag_service import RAGService


def main():

    db = SessionLocal()

    try:

        rag = RAGService(db)

        question = "What is Saudi Vision 2030?"

        response = rag.ask(
            question=question,
            knowledge_base_id=5,
        )

        print("=" * 80)
        print("QUESTION")
        print("=" * 80)
        print(question)

        print("\n")

        print("=" * 80)
        print("ANSWER")
        print("=" * 80)
        print(response["answer"])

        print("\n")

        print("=" * 80)
        print("SOURCES")
        print("=" * 80)

        for index, source in enumerate(response["sources"], start=1):

            print(f"\nSource {index}")

            print(f"Score              : {source['score']:.4f}")

            print(f"Chunk UUID         : {source['chunk_uuid']}")

            print(
                f"Parsed Document ID : {source['parsed_document_id']}"
            )

    finally:

        db.close()


if __name__ == "__main__":
    main()