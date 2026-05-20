"""Knowledge-graph access interface for the DietIBD-KG."""
from __future__ import annotations

from neo4j import GraphDatabase

from dietibdkg import config


class KnowledgeGraph:
    """Query interface to the DietIBD-KG Neo4j database.

    Example:
        >>> from dietibdkg import KnowledgeGraph
        >>> with KnowledgeGraph() as kg:
        ...     ent = kg.get_entity("resveratrol")
        ...     edges = kg.get_edges(subject="resveratrol",
        ...                          predicate="DECREASES_MARKER")
        ...     path = kg.shortest_path("resveratrol", "ulcerative colitis")

    Entity arguments accept either a node id or an exact (case-insensitive)
    label. Edge results carry full provenance (sources, confidence, and
    for literature-derived edges the evidence PMID and span).
    """

    def __init__(self, uri=None, user=None, password=None):
        self._driver = GraphDatabase.driver(
            uri or config.NEO4J_URI,
            auth=(user or config.NEO4J_USER, password or config.NEO4J_PASSWORD),
        )

    def close(self):
        """Close the database connection."""
        self._driver.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ── internal helpers ──
    def _run(self, cypher, **params):
        with self._driver.session() as s:
            return [r.data() for r in s.run(cypher, **params)]

    def _resolve_id(self, id_or_label):
        """Resolve a string to a node id (accepts exact id or exact label)."""
        rows = self._run(
            """
            MATCH (n) WHERE n.id = $x OR toLower(n.label) = toLower($x)
            RETURN n.id AS id LIMIT 1
            """,
            x=id_or_label,
        )
        if not rows:
            raise KeyError(f"No entity found for: {id_or_label!r}")
        return rows[0]["id"]

    # ── entity lookup ──
    def get_entity(self, id_or_label):
        """Return a single entity dict (id, label, type), or None."""
        rows = self._run(
            """
            MATCH (n) WHERE n.id = $x OR toLower(n.label) = toLower($x)
            RETURN n.id AS id, n.label AS label, labels(n)[0] AS type LIMIT 1
            """,
            x=id_or_label,
        )
        return rows[0] if rows else None

    def search_entities(self, name, entity_type=None, limit=20):
        """Case-insensitive substring search over entity labels.

        Optionally restrict to an entity_type (Food, Microbe, Bioactive,
        IBD_Outcome, Pathway).
        """
        type_filter = "AND labels(n)[0] = $etype" if entity_type else ""
        cypher = f"""
            MATCH (n) WHERE toLower(n.label) CONTAINS toLower($name)
            {type_filter}
            RETURN n.id AS id, n.label AS label, labels(n)[0] AS type
            ORDER BY size(n.label) LIMIT $limit
        """
        params = {"name": name, "limit": limit}
        if entity_type:
            params["etype"] = entity_type
        return self._run(cypher, **params)

    # ── neighbourhood ──
    def neighbors(self, entity, rel_type=None, direction="both", limit=100):
        """Return entities connected to the given entity.

        direction: 'out', 'in', or 'both'. rel_type optionally filters by
        relationship type (e.g. 'PRODUCES').
        """
        node_id = self._resolve_id(entity)
        arrow = {"out": "-[r]->", "in": "<-[r]-", "both": "-[r]-"}[direction]
        rel_filter = "WHERE type(r) = $rel" if rel_type else ""
        cypher = f"""
            MATCH (n {{id: $id}}){arrow}(m)
            {rel_filter}
            RETURN m.id AS id, m.label AS label, labels(m)[0] AS type,
                   type(r) AS predicate
            LIMIT $limit
        """
        params = {"id": node_id, "limit": limit}
        if rel_type:
            params["rel"] = rel_type
        return self._run(cypher, **params)

    # ── edges with provenance ──
    def get_edges(self, subject=None, predicate=None, obj=None,
                  min_confidence=None, limit=100):
        """Query edges with optional filters.

        Each result includes subject, predicate, object, sources,
        confidence, and (for literature edges) evidence_pmid,
        evidence_type, evidence_span.
        """
        wheres, params = [], {"limit": limit}
        if subject:
            params["subj"] = self._resolve_id(subject)
            wheres.append("s.id = $subj")
        if obj:
            params["obj"] = self._resolve_id(obj)
            wheres.append("o.id = $obj")
        if predicate:
            params["pred"] = predicate
            wheres.append("type(r) = $pred")
        if min_confidence is not None:
            params["minconf"] = min_confidence
            wheres.append("r.confidence >= $minconf")
        where = ("WHERE " + " AND ".join(wheres)) if wheres else ""
        cypher = f"""
            MATCH (s)-[r]->(o)
            {where}
            RETURN s.label AS subject, type(r) AS predicate, o.label AS object,
                   r.sources AS sources, r.confidence AS confidence,
                   r.evidence_pmid AS evidence_pmid,
                   r.evidence_type AS evidence_type,
                   r.evidence_span AS evidence_span
            LIMIT $limit
        """
        return self._run(cypher, **params)

    # ── paths ──
    def shortest_path(self, source, target, max_hops=5):
        """Return the shortest undirected path between two entities.

        Result is a dict with 'nodes' (label sequence) and 'rels'
        (relationship-type sequence), or None if no path exists.
        """
        src = self._resolve_id(source)
        tgt = self._resolve_id(target)
        cypher = f"""
            MATCH (a {{id: $src}}), (b {{id: $tgt}}),
                  p = shortestPath((a)-[*..{int(max_hops)}]-(b))
            RETURN [n IN nodes(p) | n.label] AS nodes,
                   [r IN relationships(p) | type(r)] AS rels
        """
        rows = self._run(cypher, src=src, tgt=tgt)
        return rows[0] if rows else None

    # ── statistics ──
    def stats(self):
        """Return summary statistics of the KG."""
        total_n = self._run("MATCH (n) RETURN count(n) AS c")[0]["c"]
        total_e = self._run("MATCH ()-[r]->() RETURN count(r) AS c")[0]["c"]
        nodes = self._run(
            "MATCH (n) UNWIND labels(n) AS l RETURN l AS type, count(*) AS c"
        )
        edges = self._run(
            "MATCH ()-[r]->() RETURN type(r) AS predicate, count(*) AS c"
        )
        return {
            "total_nodes": total_n,
            "total_edges": total_e,
            "nodes_by_type": {r["type"]: r["c"] for r in nodes},
            "edges_by_predicate": {r["predicate"]: r["c"] for r in edges},
        }
