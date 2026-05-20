"""Smoke tests for the dietibdkg package.

Requires a running Neo4j instance with the DietIBD-KG loaded.
Run with:  pytest tests/
"""
import pytest

from dietibdkg import KnowledgeGraph


@pytest.fixture(scope="module")
def kg():
    with KnowledgeGraph() as k:
        yield k


def test_stats(kg):
    s = kg.stats()
    assert s["total_nodes"] > 4000
    assert s["total_edges"] > 15000
    assert "Food" in s["nodes_by_type"]
    assert "DECREASES_MARKER" in s["edges_by_predicate"]


def test_get_entity(kg):
    ent = kg.get_entity("ulcerative colitis")
    assert ent is not None
    assert ent["type"] == "IBD_Outcome"


def test_get_entity_missing(kg):
    assert kg.get_entity("definitely not a real entity xyz") is None


def test_search_entities(kg):
    results = kg.search_entities("colitis", limit=5)
    assert len(results) > 0
    assert all("colitis" in r["label"].lower() for r in results)


def test_get_edges(kg):
    edges = kg.get_edges(predicate="DECREASES_MARKER", limit=10)
    assert len(edges) > 0
    assert all(e["predicate"] == "DECREASES_MARKER" for e in edges)


def test_neighbors(kg):
    n = kg.neighbors("ulcerative colitis", limit=10)
    assert len(n) > 0
