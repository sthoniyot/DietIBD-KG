"""Configuration module — loads environment variables and project paths."""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# API keys
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
NCBI_EMAIL = os.getenv("NCBI_EMAIL")
NCBI_API_KEY = os.getenv("NCBI_API_KEY")

# Neo4j
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")

# Paths
DATA_ROOT = PROJECT_ROOT / "data"
RAW_DATA = DATA_ROOT / "raw"
PROCESSED_DATA = DATA_ROOT / "processed"
ONTOLOGY_DATA = DATA_ROOT / "ontologies"
GOLD_STANDARD = DATA_ROOT / "gold_standard"
LOGS_DIR = PROJECT_ROOT / "logs"

# Validation
def validate_config():
    """Check that required environment variables are set."""
    missing = []
    if not OPENAI_API_KEY:
        missing.append("OPENAI_API_KEY")
    if not NCBI_EMAIL:
        missing.append("NCBI_EMAIL")
    if not NEO4J_PASSWORD:
        missing.append("NEO4J_PASSWORD")
    if missing:
        raise ValueError(f"Missing required env vars: {missing}")
    print("✓ Configuration validated")

if __name__ == "__main__":
    validate_config()
    print(f"Project root: {PROJECT_ROOT}")
    print(f"Data root: {DATA_ROOT}")
    print(f"Neo4j URI: {NEO4J_URI}")
