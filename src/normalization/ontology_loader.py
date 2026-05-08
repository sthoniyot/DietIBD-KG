"""Unified ontology loader — handles both .owl and .obo files.

Provides cascaded matching: exact label > exact synonym > tokenized > substring.
Always returns matches ranked by match quality.
"""
import re
import warnings
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import ONTOLOGY_DATA

warnings.filterwarnings("ignore", category=UnicodeWarning)


def load_owl(filepath):
    """Load an OWL file with owlready2."""
    from owlready2 import get_ontology
    onto = get_ontology(f"file://{filepath}").load()
    entries = []
    for cls in onto.classes():
        raw_id = cls.iri.split("/")[-1]
        cls_id = raw_id.replace("_", ":") if "_" in raw_id else raw_id
        label = str(cls.label[0]) if cls.label else None
        synonyms = []
        for attr in ("hasExactSynonym", "hasRelatedSynonym", "hasNarrowSynonym"):
            if hasattr(cls, attr):
                synonyms.extend([str(s) for s in getattr(cls, attr)])
        entries.append((cls_id, label, synonyms))
    return entries


def load_obo(filepath):
    """Load an OBO file with pronto. Distinguishes synonym scopes."""
    import pronto
    onto = pronto.Ontology(str(filepath))
    entries = []
    for term in onto.terms():
        # Pronto distinguishes synonym scopes: EXACT, BROAD, NARROW, RELATED
        # We separate exact synonyms because they're high-confidence matches
        exact_synonyms = []
        other_synonyms = []
        for syn in term.synonyms:
            scope = str(syn.scope).upper() if syn.scope else "RELATED"
            if scope == "EXACT":
                exact_synonyms.append(str(syn.description))
            else:
                other_synonyms.append(str(syn.description))
        # Store as a dict so we keep scope info
        synonyms = {"exact": exact_synonyms, "other": other_synonyms}
        entries.append((term.id, term.name, synonyms))
    return entries


def load_ontology(filename):
    """Auto-detect format and load. Returns list of (id, label, synonyms_dict_or_list)."""
    filepath = ONTOLOGY_DATA / filename
    if not filepath.exists():
        raise FileNotFoundError(f"Ontology not found: {filepath}")
    suffix = filepath.suffix.lower()
    if suffix == ".owl":
        return load_owl(filepath)
    elif suffix == ".obo":
        return load_obo(filepath)
    else:
        raise ValueError(f"Unknown ontology format: {suffix}")


def _normalize(text):
    """Lowercase, strip, collapse whitespace, remove punctuation."""
    if not text:
        return ""
    text = text.lower().strip()
    text = re.sub(r"[\(\)\[\]'\"]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text


def _get_exact_synonyms(synonyms):
    """Extract exact synonyms regardless of storage format (dict or list)."""
    if isinstance(synonyms, dict):
        return synonyms.get("exact", [])
    return synonyms  # list of synonyms (treated as exact for OWL)


def _get_all_synonyms(synonyms):
    """Extract all synonyms regardless of storage format."""
    if isinstance(synonyms, dict):
        return synonyms.get("exact", []) + synonyms.get("other", [])
    return synonyms


def search_ontology(entries, query, max_results=5, return_match_type=False):
    """Cascaded ontology search.

    Match priority (highest first):
        1. exact_label   — query == label (case-insensitive, normalized)
        2. exact_synonym — query is in exact synonyms
        3. label_starts  — label starts with query (e.g. "butyrate" matches "butyrate (anion)")
        4. tokenized     — query words appear as whole tokens in label
        5. substring     — query appears as substring in label or any synonym (last resort)

    Args:
        entries: List from load_ontology
        query: Search string
        max_results: Max results to return
        return_match_type: If True, returns list of (id, label, synonyms, match_type) tuples

    Returns:
        Sorted by match quality, best first.
    """
    q_norm = _normalize(query)
    q_tokens = set(q_norm.split())

    by_priority = {1: [], 2: [], 3: [], 4: [], 5: []}

    for entry_id, label, synonyms in entries:
        label_norm = _normalize(label) if label else ""

        # Tier 1: exact label match
        if label_norm == q_norm:
            by_priority[1].append((entry_id, label, synonyms, "exact_label"))
            continue

        # Tier 2: exact synonym match
        exact_syns_norm = [_normalize(s) for s in _get_exact_synonyms(synonyms)]
        if q_norm in exact_syns_norm:
            by_priority[2].append((entry_id, label, synonyms, "exact_synonym"))
            continue

        # Tier 3: label starts with query (handles "butyrate" matching "butyrate (anion)")
        if label_norm.startswith(q_norm + " ") or label_norm.startswith(q_norm + "(") or label_norm == q_norm:
            by_priority[3].append((entry_id, label, synonyms, "label_starts_with"))
            continue

        # Tier 4: tokenized — all query tokens appear as whole tokens in label
        if q_tokens and label_norm:
            label_tokens = set(label_norm.split())
            if q_tokens.issubset(label_tokens):
                by_priority[4].append((entry_id, label, synonyms, "tokenized_label"))
                continue

        # Tier 5: substring fallback (lowest confidence)
        if label_norm and q_norm in label_norm:
            by_priority[5].append((entry_id, label, synonyms, "substring_label"))
            continue

        all_syns_norm = [_normalize(s) for s in _get_all_synonyms(synonyms)]
        if any(q_norm in s for s in all_syns_norm):
            by_priority[5].append((entry_id, label, synonyms, "substring_synonym"))

    # Concatenate by priority
    ordered = []
    for tier in sorted(by_priority.keys()):
        ordered.extend(by_priority[tier])
        if len(ordered) >= max_results:
            break
    ordered = ordered[:max_results]

    if return_match_type:
        return ordered
    return [(eid, lab, syn) for eid, lab, syn, _ in ordered]


if __name__ == "__main__":
    print("Testing improved ontology loader with cascaded matching:\n")

    test_cases = [
        ("doid.obo", ["Crohn's disease", "ulcerative colitis", "inflammatory bowel disease"]),
        ("chebi.obo", ["butyrate", "propionate", "acetate", "curcumin"]),
        ("foodon.owl", ["flaxseed", "broccoli", "yogurt"]),
    ]

    for fname, queries in test_cases:
        print(f"\n{'='*60}")
        print(f"Loading {fname}...")
        entries = load_ontology(fname)
        print(f"  {len(entries):,} terms loaded\n")

        for q in queries:
            print(f"  Query: '{q}'")
            results = search_ontology(entries, q, max_results=3, return_match_type=True)
            if not results:
                print(f"    (no matches)")
            for eid, label, _, match_type in results:
                marker = "✓" if match_type in ("exact_label", "exact_synonym") else "?"
                print(f"    {marker} [{match_type:<18}] {eid}: {label}")
            print()
