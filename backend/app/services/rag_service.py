import logging

from sqlalchemy.orm import Session

from app.services.search_service import SearchService
from app.services.prompt_builder import PromptBuilder
from app.services.llm import LLMFactory

logger = logging.getLogger(__name__)


class RAGService:
    """
    Enterprise Retrieval-Augmented Generation Service.

    Responsibilities:
    - Retrieve relevant document chunks
    - Build grounded prompts
    - Generate answers using the configured LLM
    """

    def __init__(self, db: Session):

        self.db = db

        self.search_service = SearchService(db)

        self.llm = LLMFactory.get_provider()

    def ask(
        self,
        question: str,
        knowledge_base_id: int,
    ) -> dict:

        logger.info("Starting RAG pipeline...")

        # ------------------------------------------
        # Step 1: Semantic Search
        # ------------------------------------------

        results = self.search_service.semantic_search(
            query=question,
            knowledge_base_id=knowledge_base_id,
        )
        print("=" * 60)
        print("QUESTION:", question)
        print("KB ID:", knowledge_base_id)
        print("RESULT TYPE:", type(results))
        print("RESULT LENGTH:", len(results))

        if len(results) > 0:
            print("FIRST RESULT SCORE:", results[0].score)
            print("FIRST RESULT TEXT:")
            print(results[0].payload["text"][:200])

        print("=" * 60)

        if not results:

            logger.warning("No relevant chunks found.")

            return {
                "answer": "I couldn't find enough information in the uploaded documents.",
                "sources": [],
            }

        # ------------------------------------------
        # Step 2: Extract Context
        # ------------------------------------------

        contexts = [
            item.payload["text"]
            for item in results
        ]

        # ------------------------------------------
        # Step 3: Build Prompt
        # ------------------------------------------

        prompt = PromptBuilder.build_prompt(
            question=question,
            contexts=contexts,
        )

        # ------------------------------------------
        # Step 4: Generate Answer
        # ------------------------------------------

        answer = self.llm.generate(prompt)

        # ------------------------------------------
        # Step 5: Build Sources
        # ------------------------------------------

        sources = []

        for item in results:

            sources.append({

                "score": float(item.score),

                "chunk_uuid": item.payload.get("chunk_uuid"),

                "parsed_document_id": item.payload.get(
                    "parsed_document_id"
                ),

            })

        logger.info("RAG pipeline completed successfully.")

        return {

            "answer": answer,

            "sources": sources,

        }