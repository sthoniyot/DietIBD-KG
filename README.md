# dietibdkg

Access interface for the **DietIBD-KG** — a precision-nutrition knowledge
graph for inflammatory bowel disease (IBD), integrating curated databases
with LLM-extracted literature.

The knowledge graph contains 4,610 entities (foods, microbes, bioactive
compounds, IBD outcomes, pathways) and 16,172 provenance-tagged edges.

## Installation

From the project root:

    pip install -e .

For embedding support (RotatE vectors, similarity search):

    pip install -e '.[embeddings]'

A .env file at the project root must define NEO4J_URI, NEO4J_USER,
and NEO4J_PASSWORD.

## Usage

### Querying the knowledge graph

    from dietibdkg import KnowledgeGraph

    with KnowledgeGraph() as kg:
        # summary statistics
        print(kg.stats())

        # look up an entity
        ent = kg.get_entity("ulcerative colitis")

        # search by name
        kg.search_entities("colitis", entity_type="IBD_Outcome")

        # edges with provenance
        edges = kg.get_edges(predicate="DECREASES_MARKER", min_confidence=0.8)

        # neighbours
        kg.neighbors("resveratrol", rel_type="DECREASES_MARKER")

        # shortest path between two entities
        kg.shortest_path("resveratrol", "ulcerative colitis")

### Using embeddings

    from dietibdkg import Embeddings

    emb = Embeddings("rotate")
    vec = emb.get_vector("resveratrol")
    emb.most_similar("resveratrol", k=5)

## Components

- KnowledgeGraph: query entities, edges, neighbours, and paths via Neo4j.
- Embeddings: access trained KG embeddings (TransE / DistMult / RotatE);
  RotatE is the default and best-performing model.

## Knowledge graph schema

Entity types: Food, Microbe, Bioactive, IBD_Outcome, Pathway.

Relationship types include CONTAINS, PRODUCES, INCREASES_ABUNDANCE_OF,
DECREASES_ABUNDANCE_OF, INCREASED_IN, DECREASED_IN, INCREASES_MARKER,
DECREASES_MARKER, HAS_HIGH_FODMAP_CONTENT_OF, plus curated-only types
(INVOLVES, IS_LOW_FODMAP_FOOD, MODULATES_CLUSTER).

Every edge carries provenance: a sources list (curated database names or
"LLM"), a confidence score, and for literature-derived edges the evidence
PMID, evidence type, and a verbatim evidence span.
