"""Neo4j connection wrapper with batched write support.

Loads credentials from .env. Provides batched MERGE for nodes and edges,
which is much faster than per-record Cypher round-trips.

Import pattern matches Phase B convention: sys.path manipulation, no
package syntax needed.
"""
import os
import sys
from pathlib import Path

# Add project root for .env loading
_PROJECT_ROOT = Path(__file__).resolve().parents[2]

from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv(_PROJECT_ROOT / ".env")


class Neo4jClient:
    def __init__(self):
        uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        user = os.getenv("NEO4J_USER", "neo4j")
        password = os.getenv("NEO4J_PASSWORD")
        if not password:
            raise RuntimeError("NEO4J_PASSWORD not set in .env")
        self.driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self):
        self.driver.close()

    def run(self, query, **params):
        """Run a Cypher query and return results as a list of records."""
        with self.driver.session() as session:
            return list(session.run(query, **params))

    def execute_write(self, query, **params):
        """Run a write query in a managed transaction."""
        with self.driver.session() as session:
            return session.execute_write(lambda tx: list(tx.run(query, **params)))

    def batch_merge_nodes(self, label, records, batch_size=1000):
        """Batch-merge nodes via UNWIND.

        records: list of dicts with at least 'id' key plus arbitrary properties.
        Yields (count_done, total) after each batch for progress.
        """
        total = len(records)
        with self.driver.session() as session:
            for i in range(0, total, batch_size):
                batch = records[i:i + batch_size]
                query = f"""
                UNWIND $batch AS row
                MERGE (n:{label} {{id: row.id}})
                SET n += row
                """
                session.execute_write(lambda tx: tx.run(query, batch=batch).consume())
                yield min(i + batch_size, total), total

    def batch_merge_relationships(self, rel_type, subject_label, object_label,
                                   records, batch_size=1000):
        """Batch-merge relationships via UNWIND.

        records: list of dicts with 'subject_id', 'object_id', 'props'.
        Yields (count_done, total) after each batch.
        """
        total = len(records)
        with self.driver.session() as session:
            for i in range(0, total, batch_size):
                batch = records[i:i + batch_size]
                query = f"""
                UNWIND $batch AS row
                MATCH (s:{subject_label} {{id: row.subject_id}})
                MATCH (o:{object_label} {{id: row.object_id}})
                MERGE (s)-[r:{rel_type}]->(o)
                SET r += row.props
                """
                session.execute_write(lambda tx: tx.run(query, batch=batch).consume())
                yield min(i + batch_size, total), total
