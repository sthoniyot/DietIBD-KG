"""Unified Triple data structure for DietIBD-KG.

Every ingestion script (Disbiome, gutMDisorder, FooDB, KEGG, LLM-extracted)
produces records in this format. Columns are stable across sources.
"""
from dataclasses import dataclass, asdict, field
from typing import Optional


@dataclass
class Triple:
    """One canonical fact in DietIBD-KG.

    Required fields:
        subject_id, subject_label, subject_type
        predicate
        object_id, object_label, object_type
        source

    Optional/contextual:
        evidence_type, confidence, source_id, publication_id, sample_type, notes
    """
    # Subject (e.g., a microbe, a food)
    subject_id: str        # Canonical ID, e.g. "NCBITaxon:853"
    subject_label: str     # Human-readable, e.g. "Faecalibacterium prausnitzii"
    subject_type: str      # One of: Microbe, Food, Bioactive, Metabolite, Cytokine, IBD_Outcome, Pathway

    # Predicate
    predicate: str         # e.g. "decreased_in", "increased_in", "ferments", "produces"

    # Object (e.g., a disease, a metabolite)
    object_id: str         # Canonical ID, e.g. "DOID:8778"
    object_label: str      # Human-readable, e.g. "Crohn's disease"
    object_type: str       # Same vocabulary as subject_type

    # Provenance
    source: str            # Originating database, e.g. "Disbiome", "gutMDisorder", "PubMed:LLM"
    source_id: Optional[str] = None        # ID within source, e.g. Disbiome experiment_id
    publication_id: Optional[str] = None   # Source publication if available

    # Evidence and confidence
    evidence_type: str = "observational"   # RCT, observational, mechanistic, review
    confidence: float = 0.5                # 0.0 to 1.0

    # Optional context
    sample_type: Optional[str] = None      # e.g. "Faeces", "Tissue biopsy"
    notes: Optional[str] = None
    method: Optional[str] = None           # e.g. "16S rRNA sequencing"

    def to_dict(self):
        return asdict(self)

    def __post_init__(self):
        # Validate confidence is in range
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be in [0,1], got {self.confidence}")
        # Validate types are from known vocabulary
        valid_types = {"Microbe", "Food", "Bioactive", "Metabolite",
                       "Cytokine", "IBD_Outcome", "Pathway", "Disease"}
        if self.subject_type not in valid_types:
            raise ValueError(f"subject_type '{self.subject_type}' not in {valid_types}")
        if self.object_type not in valid_types:
            raise ValueError(f"object_type '{self.object_type}' not in {valid_types}")


def write_triples_tsv(triples, output_path):
    """Write a list of Triple objects to TSV. First column row is the header."""
    import csv
    if not triples:
        return
    fields = list(asdict(triples[0]).keys())
    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        for t in triples:
            writer.writerow(t.to_dict())


def read_triples_tsv(input_path):
    """Read a TSV file of triples back into a list of Triple objects."""
    import csv
    triples = []
    with open(input_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            # Convert empty strings to None where appropriate
            for k in ["source_id", "publication_id", "sample_type", "notes", "method"]:
                if row.get(k) == "":
                    row[k] = None
            row["confidence"] = float(row["confidence"])
            triples.append(Triple(**row))
    return triples


if __name__ == "__main__":
    # Self-test
    t = Triple(
        subject_id="NCBITaxon:853",
        subject_label="Faecalibacterium prausnitzii",
        subject_type="Microbe",
        predicate="decreased_in",
        object_id="DOID:8778",
        object_label="Crohn's disease",
        object_type="IBD_Outcome",
        source="Disbiome",
        source_id="20",
        publication_id="3",
        evidence_type="observational",
        confidence=0.85,
        sample_type="Faeces",
        method="DGGE",
    )
    print("Sample triple:")
    for k, v in t.to_dict().items():
        print(f"  {k}: {v}")
