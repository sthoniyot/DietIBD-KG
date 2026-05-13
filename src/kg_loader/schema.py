"""Neo4j schema for DietIBD-KG.

Creates uniqueness constraints (one node per id within a label) and
indexes for query performance. Idempotent - safe to re-run.

Run with:
    python src/kg_loader/schema.py
"""
import sys
from pathlib import Path

# Add src/ to path so we can import siblings (matches Phase B pattern)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kg_loader.neo4j_client import Neo4jClient

# All node labels we use in the KG
NODE_LABELS = [
    "Food",
    "Bioactive",
    "Metabolite",
    "Microbe",
    "Cytokine",
    "IBD_Outcome",
    "Pathway",
    "Disease",
]

# Property indexes (for filtering and lookups beyond the id constraint)
PROPERTY_INDEXES = [
    ("Food", "label"),
    ("Bioactive", "label"),
    ("Microbe", "label"),
    ("Microbe", "rank"),
    ("IBD_Outcome", "label"),
    ("Pathway", "label"),
]


def setup_schema(client):
    """Create constraints and indexes. Idempotent."""
    print("Creating uniqueness constraints...")
    for label in NODE_LABELS:
        constraint_name = f"unique_{label.lower()}_id"
        query = f"""
        CREATE CONSTRAINT {constraint_name} IF NOT EXISTS
        FOR (n:{label}) REQUIRE n.id IS UNIQUE
        """
        client.execute_write(query)
        print(f"  {constraint_name}")

    print("\nCreating property indexes...")
    for label, prop in PROPERTY_INDEXES:
        index_name = f"idx_{label.lower()}_{prop}"
        query = f"""
        CREATE INDEX {index_name} IF NOT EXISTS
        FOR (n:{label}) ON (n.{prop})
        """
        client.execute_write(query)
        print(f"  {index_name}")

    print("\nSchema setup complete.")


def show_schema(client):
    """Print the current schema state."""
    print("=== Current constraints ===")
    for row in client.run("SHOW CONSTRAINTS YIELD name, type, labelsOrTypes, properties"):
        print(f"  {row['name']:<30} {row['type']:<25} {row['labelsOrTypes']} {row['properties']}")

    print("\n=== Current indexes ===")
    for row in client.run(
        "SHOW INDEXES YIELD name, type, labelsOrTypes, properties WHERE type <> 'LOOKUP'"
    ):
        print(f"  {row['name']:<30} {row['type']:<15} {row['labelsOrTypes']} {row['properties']}")


if __name__ == "__main__":
    client = Neo4jClient()
    try:
        setup_schema(client)
        print()
        show_schema(client)
    finally:
        client.close()
