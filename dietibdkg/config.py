"""Configuration: Neo4j connection settings and artifact paths.

Connection settings are read from a .env file at the project root.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

_PKG_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = _PKG_DIR.parent

load_dotenv(PROJECT_ROOT / ".env")

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")

EMBEDDINGS_DIR = PROJECT_ROOT / "data" / "processed" / "embeddings"
TRIPLES_FILE = EMBEDDINGS_DIR / "kg_triples.tsv"
DEFAULT_EMBEDDING_MODEL = "rotate"
