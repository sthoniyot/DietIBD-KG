"""dietibdkg — access interface for the DietIBD-KG knowledge graph.

The DietIBD-KG is a precision-nutrition knowledge graph for inflammatory
bowel disease, integrating curated databases with LLM-extracted literature.

Main entry points:
    KnowledgeGraph : query entities, edges, neighbours, and paths
    Embeddings     : access trained KG embeddings (requires the
                     'embeddings' optional dependency)
"""
from dietibdkg.kg import KnowledgeGraph
from dietibdkg.embeddings import Embeddings

__version__ = "0.1.0"
__all__ = ["KnowledgeGraph", "Embeddings"]
