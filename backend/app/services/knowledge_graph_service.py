"""
KnowledgeGraphService — PostgreSQL-Backed Knowledge Relationship Graph.

Refinement #9:
- Uses PostgreSQL relational graph queries initially.
- Clean interface designed to allow future migration to Neo4j / Graph DBs.
- Responsibilities: Connected documents, related policies, reference graph, dependency graph.
"""

import logging
from typing import List, Dict, Any, Set
from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.document_relationship import DocumentRelationship
from app.models.document_metadata import DocumentMetadata

logger = logging.getLogger(__name__)


class KnowledgeGraphService:
    def __init__(self, db: Session):
        self.db = db

    def get_document_subgraph(self, document_id: int, max_depth: int = 2) -> Dict[str, Any]:
        """
        Traverse inter-document relationships starting from document_id up to max_depth.
        Returns graph representation: {"nodes": [...], "edges": [...]}.
        """
        visited_doc_ids: Set[int] = set()
        nodes: List[Dict[str, Any]] = []
        edges: List[Dict[str, Any]] = []

        queue = [(document_id, 0)]
        visited_doc_ids.add(document_id)

        while queue:
            curr_id, depth = queue.pop(0)

            # Fetch document node info
            doc = self.db.query(Document).filter(Document.id == curr_id).first()
            if doc:
                meta = (
                    self.db.query(DocumentMetadata)
                    .filter(DocumentMetadata.document_id == curr_id)
                    .first()
                )
                nodes.append({
                    "id": doc.id,
                    "uuid": str(doc.uuid),
                    "filename": doc.filename,
                    "classification": doc.classification or "Technical Documentation",
                    "title": meta.title if meta else doc.filename,
                    "mime_type": doc.mime_type,
                    "language": doc.language or "EN",
                })

            if depth >= max_depth:
                continue

            # Fetch outgoing and incoming edges
            relationships = (
                self.db.query(DocumentRelationship)
                .filter(
                    (DocumentRelationship.source_document_id == curr_id)
                    | (DocumentRelationship.target_document_id == curr_id)
                )
                .all()
            )

            for rel in relationships:
                edges.append({
                    "id": rel.id,
                    "source": rel.source_document_id,
                    "target": rel.target_document_id,
                    "type": rel.relationship_type,
                    "score": rel.similarity_score,
                })

                neighbor_id = (
                    rel.target_document_id
                    if rel.source_document_id == curr_id
                    else rel.source_document_id
                )

                if neighbor_id not in visited_doc_ids:
                    visited_doc_ids.add(neighbor_id)
                    queue.append((neighbor_id, depth + 1))

        # Deduplicate edges by ID
        unique_edges = {e["id"]: e for e in edges}.values()

        return {
            "root_id": document_id,
            "nodes": nodes,
            "edges": list(unique_edges),
        }

    def get_related_policies(self, document_id: int) -> List[Dict[str, Any]]:
        """Find policies related to a document via graph relationships or classification."""
        subgraph = self.get_document_subgraph(document_id, max_depth=2)
        policy_nodes = [
            n for n in subgraph["nodes"]
            if n["id"] != document_id and n["classification"] in ["Policies", "Legal", "Contracts"]
        ]
        return policy_nodes
