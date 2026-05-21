"""Build the DietIBD-KG release bundle for Zenodo deposition.

Exports the knowledge graph to tool-agnostic formats, extracts RotatE
entity embeddings, generates a data descriptor and statistics, writes a
license file, and assembles everything into a versioned zipped bundle.

Usage:
    python src/release/build_release.py
"""
import csv
import json
import shutil
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

VERSION = "1.1.0"
RELEASE_ROOT = PROJECT_ROOT / "release"
BUNDLE = RELEASE_ROOT / f"dietibdkg-v{VERSION}"
TRIPLES_SRC = PROJECT_ROOT / "data" / "processed" / "embeddings" / "kg_triples.tsv"


def get_driver():
    import os
    return GraphDatabase.driver(
        os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD")),
    )


def export_nodes(drv, path):
    with drv.session() as s, open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["id", "label", "type", "origin"])
        n = 0
        for r in s.run("""
            MATCH (n)
            RETURN n.id AS id, n.label AS label, labels(n)[0] AS type,
                   n.source AS source
            ORDER BY type, label
        """):
            origin = "LLM" if r["source"] == "LLM" else "curated"
            w.writerow([r["id"], r["label"], r["type"], origin])
            n += 1
    return n


def export_edges(drv, path):
    with drv.session() as s, open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow([
            "subject_id", "subject_label", "predicate",
            "object_id", "object_label", "sources", "confidence",
            "evidence_count", "evidence_types", "evidence_pmid",
            "evidence_type", "evidence_span",
        ])
        n = 0
        for r in s.run("""
            MATCH (s)-[r]->(o)
            RETURN s.id AS sid, s.label AS slabel, type(r) AS pred,
                   o.id AS oid, o.label AS olabel,
                   r.sources AS sources, r.confidence AS conf,
                   r.evidence_count AS ecount, r.evidence_types AS etypes,
                   r.evidence_pmid AS pmid, r.evidence_type AS etype,
                   r.evidence_span AS espan
            ORDER BY pred, slabel
        """):
            sources = "|".join(r["sources"]) if r["sources"] else ""
            etypes = "|".join(r["etypes"]) if r["etypes"] else ""
            w.writerow([
                r["sid"], r["slabel"], r["pred"], r["oid"], r["olabel"],
                sources, r["conf"], r["ecount"], etypes,
                r["pmid"] or "", r["etype"] or "", r["espan"] or "",
            ])
            n += 1
    return n


def export_embeddings(path):
    import torch
    from pykeen.triples import TriplesFactory

    model_path = (PROJECT_ROOT / "data" / "processed" / "embeddings"
                  / "rotate" / "trained_model.pkl")
    if not model_path.exists():
        print(f"  WARNING: RotatE model not found at {model_path} - skipping")
        return None

    model = torch.load(model_path, weights_only=False, map_location="cpu")
    tf = TriplesFactory.from_path(str(TRIPLES_SRC))
    id_to_entity = {v: k for k, v in tf.entity_to_id.items()}

    emb = model.entity_representations[0]().detach().cpu()
    if torch.is_complex(emb):
        emb = torch.cat([emb.real, emb.imag], dim=-1)
    emb = emb.numpy()

    dim = emb.shape[1]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["entity_id"] + [f"d{i}" for i in range(dim)])
        for idx in range(emb.shape[0]):
            w.writerow([id_to_entity[idx]] +
                       [f"{x:.6f}" for x in emb[idx]])
    return emb.shape


def gather_stats(drv):
    with drv.session() as s:
        tn = s.run("MATCH (n) RETURN count(n) AS c").single()["c"]
        te = s.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
        nbt = {r["t"]: r["c"] for r in s.run(
            "MATCH (n) UNWIND labels(n) AS l "
            "RETURN l AS t, count(*) AS c ORDER BY c DESC")}
        ebp = {r["p"]: r["c"] for r in s.run(
            "MATCH ()-[r]->() RETURN type(r) AS p, count(*) AS c "
            "ORDER BY c DESC")}
        ebs = {}
        for r in s.run("MATCH ()-[r]->() UNWIND r.sources AS src "
                       "RETURN src, count(*) AS c ORDER BY c DESC"):
            ebs[r["src"]] = r["c"]
    return {"total_nodes": tn, "total_edges": te,
            "nodes_by_type": nbt, "edges_by_predicate": ebp,
            "edges_by_source": ebs}


def write_descriptor(path, stats, emb_shape):
    dim = emb_shape[1] if emb_shape else "n/a"
    nbt = "\n".join(f"- {k}: {v:,}" for k, v in stats["nodes_by_type"].items())
    ebs = "\n".join(f"- {k}: {v:,}" for k, v in stats["edges_by_source"].items())
    text = f"""# DietIBD-KG - Data Descriptor

Version: {VERSION}
Release date: {datetime.now().strftime('%Y-%m-%d')}

## Overview

DietIBD-KG is a precision-nutrition knowledge graph for inflammatory bowel
disease (IBD). It integrates curated biomedical databases with
relationships extracted from the published literature using a large
language model, linking foods, bioactive compounds, gut microbes,
metabolic pathways, and IBD outcomes.

## Contents

- nodes.tsv: all {stats['total_nodes']:,} entities (id, label, type, origin)
- edges.tsv: all {stats['total_edges']:,} edges with full provenance
- kg_triples.tsv: (subject, predicate, object) triples for embedding training
- embeddings_rotate.tsv: RotatE entity embeddings ({dim}-d real vectors)
- STATISTICS.json: summary statistics
- DATA_DESCRIPTOR.md: this file
- LICENSE.txt: license terms

## Construction

Curated layer: relationships ingested from FooDB (food composition), KEGG
(metabolic pathways), Disbiome (microbe-disease associations), Bolte et al.
2021 (diet-microbiome associations), and a FODMAP content consensus
compilation.

Literature layer: relationships extracted from 8,219 PubMed abstracts
using a large language model under a fixed predicate schema. The
extraction pipeline was validated against a manually annotated gold
standard of 87 abstracts, achieving F1 = 0.567 on a held-out test set.

The combined graph underwent quality assurance: schema validation,
node-type correction, and removal of mis-extracted edges.

## Schema

Entity types: Food, Bioactive, Microbe, IBD_Outcome, Pathway.

Core relationship types: CONTAINS, PRODUCES, INCREASES_ABUNDANCE_OF,
DECREASES_ABUNDANCE_OF, INCREASED_IN, DECREASED_IN, INCREASES_MARKER,
DECREASES_MARKER, HAS_HIGH_FODMAP_CONTENT_OF. Curated-only types: INVOLVES,
IS_LOW_FODMAP_FOOD, MODULATES_CLUSTER.

## Provenance

Every edge carries a sources field (curated database name(s) or "LLM"), a
confidence score, and an evidence_count. Literature-derived edges
additionally carry an evidence_pmid (source PubMed article), an
evidence_type (study design), and an evidence_span (verbatim supporting
text from the source abstract).

## Embeddings

Knowledge-graph embeddings were trained with PyKEEN. Three models were
evaluated by link prediction (TransE, DistMult, RotatE); RotatE performed
best (MRR 0.494, Hits@10 0.633). RotatE uses 256-dimensional complex
embeddings; the released vectors concatenate real and imaginary parts into
{dim}-dimensional real vectors.

## Statistics

Total nodes: {stats['total_nodes']:,}
Total edges: {stats['total_edges']:,}

Nodes by type:
{nbt}

Edges by source:
{ebs}

## Source attribution

This resource incorporates data derived from FooDB (https://foodb.ca),
KEGG (https://www.kegg.jp), Disbiome (https://disbiome.ugent.be), Bolte et
al. 2021 (Gut), and a FODMAP content consensus compilation.
Literature-derived edges are extracted from PubMed abstracts and cite
their source article by PMID. Users should consult and comply with the
licensing terms of each upstream source.

## Limitations

- Literature-extracted edges reflect an automated pipeline with measured
  F1 = 0.567; a subset may contain extraction errors. The confidence and
  evidence fields support filtering.
- The KG represents reported associations, not validated causal claims.
- Coverage reflects the source databases and the abstract corpus; it is
  not exhaustive.

## Citation

If you use DietIBD-KG, please cite the associated publication and this
Zenodo deposit.

## License

Released under the Creative Commons Attribution 4.0 International license
(CC-BY-4.0). See LICENSE.txt.
"""
    Path(path).write_text(text, encoding="utf-8")


def write_license(path):
    text = """DietIBD-KG is released under the Creative Commons Attribution 4.0
International License (CC-BY-4.0).

You are free to share and adapt this material for any purpose, provided
you give appropriate credit.

Full license text: https://creativecommons.org/licenses/by/4.0/legalcode

Note: this resource incorporates data derived from third-party sources
(FooDB, KEGG, Disbiome, Bolte et al. 2021, FODMAP consensus compilation,
and PubMed abstracts). Users are responsible for complying with the
licensing terms of those upstream sources.
"""
    Path(path).write_text(text, encoding="utf-8")


def write_zenodo_metadata(path, stats):
    text = f"""# Zenodo Deposit Metadata - copy into the Zenodo upload form

Title:
  DietIBD-KG: A Precision-Nutrition Knowledge Graph for Inflammatory
  Bowel Disease

Version: {VERSION}

Resource type: Dataset

Authors:
  Thoniyot, Sharath - BITS Pilani, Dubai Campus

Description:
  DietIBD-KG is a precision-nutrition knowledge graph for inflammatory
  bowel disease (IBD), integrating curated biomedical databases with
  relationships extracted from {stats['total_edges']:,} ... see
  DATA_DESCRIPTOR.md. The graph contains {stats['total_nodes']:,} entities
  and {stats['total_edges']:,} provenance-tagged edges linking foods,
  bioactive compounds, gut microbes, pathways, and IBD outcomes, with
  trained RotatE embeddings.

Keywords:
  knowledge graph; inflammatory bowel disease; precision nutrition;
  gut microbiome; diet; bioactive compounds; literature mining

License: Creative Commons Attribution 4.0 International (CC-BY-4.0)

Related identifiers:
  - (add) GitHub repository URL
  - (add) associated publication DOI once available
"""
    Path(path).write_text(text, encoding="utf-8")


def main():
    print(f"Building DietIBD-KG release v{VERSION}...")
    if BUNDLE.exists():
        shutil.rmtree(BUNDLE)
    BUNDLE.mkdir(parents=True)

    drv = get_driver()
    print("Exporting nodes...")
    n_nodes = export_nodes(drv, BUNDLE / "nodes.tsv")
    print(f"  {n_nodes:,} nodes -> nodes.tsv")

    print("Exporting edges...")
    n_edges = export_edges(drv, BUNDLE / "edges.tsv")
    print(f"  {n_edges:,} edges -> edges.tsv")

    stats = gather_stats(drv)
    drv.close()

    print("Copying triples file...")
    shutil.copy(TRIPLES_SRC, BUNDLE / "kg_triples.tsv")

    print("Exporting RotatE embeddings...")
    emb_shape = export_embeddings(BUNDLE / "embeddings_rotate.tsv")
    if emb_shape:
        print(f"  {emb_shape[0]:,} entities x {emb_shape[1]} dims")

    print("Writing statistics, descriptor, license, metadata...")
    (BUNDLE / "STATISTICS.json").write_text(
        json.dumps(stats, indent=2), encoding="utf-8")
    write_descriptor(BUNDLE / "DATA_DESCRIPTOR.md", stats, emb_shape)
    write_license(BUNDLE / "LICENSE.txt")
    write_zenodo_metadata(RELEASE_ROOT / "zenodo_metadata.md", stats)

    print("Zipping bundle...")
    zip_base = str(RELEASE_ROOT / f"dietibdkg-v{VERSION}")
    shutil.make_archive(zip_base, "zip", root_dir=str(RELEASE_ROOT),
                        base_dir=f"dietibdkg-v{VERSION}")

    print(f"\n=== Release bundle built ===")
    print(f"  Directory: {BUNDLE}")
    print(f"  Zip:       {zip_base}.zip")
    print(f"  Metadata:  {RELEASE_ROOT / 'zenodo_metadata.md'}")
    for p in sorted(BUNDLE.iterdir()):
        print(f"    {p.name:30s} {p.stat().st_size:>12,} bytes")


if __name__ == "__main__":
    main()

