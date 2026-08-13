"""
RerankerService — Pluggable Re-ranking Interface.

Single Responsibility: re-rank search results by relevance to the query.

Architecture
------------
- Abstract base class (BaseReranker) defines the contract.
- Default implementation (NoOpReranker) passes results unchanged.
- Factory function (get_reranker) returns the configured implementation.
- Pipeline does NOT change when swapping implementations.

Future Implementations
----------------------
- BGEReranker (BAAI/bge-reranker-v2-m3)
- CrossEncoderReranker (cross-encoder/ms-marco-MiniLM-L-12-v2)
"""

import logging
from abc import ABC, abstractmethod
from typing import List, TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.search_service import SearchResult

logger = logging.getLogger(__name__)


class BaseReranker(ABC):
    """
    Abstract base for all re-ranker implementations.

    Every re-ranker must accept a query and a list of SearchResult objects,
    and return a re-ordered list of SearchResult objects.
    """

    @abstractmethod
    def rerank(
        self,
        query: str,
        results: "List[SearchResult]",
    ) -> "List[SearchResult]":
        """
        Re-rank search results by relevance to the query.

        Parameters
        ----------
        query : str
            The user's question (possibly rewritten).
        results : list[SearchResult]
            Candidate results from hybrid search + rank fusion.

        Returns
        -------
        list[SearchResult]
            Re-ordered results, most relevant first.
        """
        ...


class NoOpReranker(BaseReranker):
    """
    No-op re-ranker — returns results unchanged.

    Default for Sprint 12. Swap with BGEReranker or CrossEncoderReranker
    in future sprints by changing the get_reranker() factory — no pipeline
    changes required.
    """

    def rerank(
        self,
        query: str,
        results: "List[SearchResult]",
    ) -> "List[SearchResult]":
        logger.debug(
            f"NoOpReranker: passing {len(results)} results unchanged"
        )
        return results


def get_reranker() -> BaseReranker:
    """
    Factory function — returns the configured re-ranker.

    Currently returns NoOpReranker. Future: inspect settings.RERANKER_TYPE
    to instantiate BGEReranker, CrossEncoderReranker, etc.
    """
    return NoOpReranker()
