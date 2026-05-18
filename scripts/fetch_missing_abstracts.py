"""Fetch the 16 missing abstracts from PubMed via Entrez and rebuild
gold_standard_to_annotate.tsv with correct PMIDs.

Reuses the parser from fetch_pubmed.py.
"""
import csv
import json
import os
import re
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from Bio import Entrez

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

Entrez.email = os.getenv("NCBI_EMAIL")
Entrez.api_key = os.getenv("NCBI_API_KEY")
if not Entrez.email or not Entrez.api_key:
    sys.exit("ERROR: NCBI credentials not set")

PROCESSED = PROJECT_ROOT / "data" / "processed"
ANNOTATIONS = PROCESSED / "gold_standard_annotations.tsv"
SOURCE_OLD = PROCESSED / "gold_standard_to_annotate.tsv"
SOURCE_NEW = PROCESSED / "gold_standard_to_annotate.tsv.fixed"
ABSTRACTS = PROJECT_ROOT / "data" / "raw" / "pubmed" / "abstracts.jsonl"
MISSING_OUT = PROJECT_ROOT / "data" / "raw" / "pubmed" / "missing_abstracts.jsonl"


def parse_article(article):
    """Same parser as fetch_pubmed.py."""
    try:
        medline = article["MedlineCitation"]
        pmid = str(medline["PMID"])
        article_data = medline["Article"]
        title = str(article_data.get("ArticleTitle", "")).strip()

        abstract_parts = []
        abstract_obj = article_data.get("Abstract", {})
        for piece in abstract_obj.get("AbstractText", []):
            text = str(piece).strip()
            label = piece.attributes.get("Label", "") if hasattr(piece, "attributes") else ""
            if label:
                abstract_parts.append(f"{label}: {text}")
            else:
                abstract_parts.append(text)
        abstract = " ".join(abstract_parts).strip()

        if not abstract or len(abstract) < 100:
            return None

        journal_obj = article_data.get("Journal", {})
        journal_title = str(journal_obj.get("Title", "")).strip()
        year = ""
        pub_date = journal_obj.get("JournalIssue", {}).get("PubDate", {})
        if "Year" in pub_date:
            year = str(pub_date["Year"])
        elif "MedlineDate" in pub_date:
            year = str(pub_date["MedlineDate"])[:4]

        doi = ""
        for aid in article_data.get("ELocationID", []):
            if aid.attributes.get("EIdType") == "doi":
                doi = str(aid)
                break

        pub_types = [str(pt) for pt in article_data.get("PublicationTypeList", [])]

        mesh_terms = []
        for mh in medline.get("MeshHeadingList", []):
            descriptor = mh.get("DescriptorName")
            if descriptor:
                mesh_terms.append(str(descriptor))

        return {
            "pmid": pmid, "title": title, "abstract": abstract,
            "journal": journal_title, "year": year, "doi": doi,
            "publication_types": pub_types, "mesh_terms": mesh_terms,
        }
    except Exception as e:
        return None


def classify(art):
    """Stratum classification."""
    mesh = set(art.get("mesh_terms", []))
    pub_types = set(art.get("publication_types", []))
    text = (art.get("title", "") + " " + art.get("abstract", "")).lower()

    is_review = "Review" in pub_types or "Systematic Review" in pub_types
    has_microbiome = ("Gastrointestinal Microbiome" in mesh or
                      "microbiom" in text or "microbiota" in text)
    has_ibd = ("Inflammatory Bowel Diseases" in mesh or "Crohn Disease" in mesh
               or "Colitis, Ulcerative" in mesh or "crohn" in text
               or "ulcerative colitis" in text)
    has_diet = ("Diet" in mesh or "diet" in text or "nutrition" in text
                or "food" in text)
    has_bioactive = any(b in text for b in [
        "butyrate", "short-chain fatty acid", "scfa", "tryptophan",
        "bile acid", "indole", "polyphenol", "omega-3", "fiber"])
    has_specific_microbe = any(m in text for m in [
        "faecalibacterium", "akkermansia", "roseburia", "bacteroides",
        "lactobacillus", "bifidobacterium"])
    is_off_scope = not (has_microbiome or has_bioactive or has_specific_microbe)

    if is_review: return "reviews"
    if is_off_scope and has_ibd: return "off_scope"
    if has_diet and has_microbiome and has_ibd: return "diet_microbiome_ibd"
    if has_specific_microbe and has_ibd: return "microbe_ibd"
    if has_bioactive and has_ibd: return "bioactive_ibd"
    return "general"


# Missing PMIDs from previous diagnostic
MISSING_PMIDS = [
    "34604245", "37424683", "36142100", "31770631", "32672323",
    "27591605", "32707338", "33240217", "34444901", "31518251",
    "33604082", "32050369", "33261541", "32915830", "32560300", "34188540",
]

print(f"Fetching {len(MISSING_PMIDS)} missing abstracts from PubMed...")
handle = Entrez.efetch(
    db="pubmed", id=",".join(MISSING_PMIDS),
    rettype="xml", retmode="xml",
)
records = Entrez.read(handle)
handle.close()

fetched = {}
for article in records.get("PubmedArticle", []):
    parsed = parse_article(article)
    if parsed:
        fetched[parsed["pmid"]] = parsed
        print(f"  ✓ {parsed['pmid']}: {parsed['title'][:80]}")

print(f"\nFetched {len(fetched)} of {len(MISSING_PMIDS)}")

missing_still = set(MISSING_PMIDS) - set(fetched.keys())
if missing_still:
    print(f"Still missing: {missing_still}")
    print("These can't be fetched (deleted/withdrawn/unreachable).")

# Append fetched abstracts to a separate file so we don't pollute Stage 2 corpus
print(f"\nSaving fetched abstracts to: {MISSING_OUT}")
with open(MISSING_OUT, "w", encoding="utf-8") as f:
    for pmid, art in fetched.items():
        f.write(json.dumps(art, ensure_ascii=False) + "\n")

# Build mapping: pmid -> art (from both files now)
abstracts_by_pmid = dict(fetched)
with open(ABSTRACTS, encoding="utf-8") as f:
    for line in f:
        try:
            art = json.loads(line)
            abstracts_by_pmid[art["pmid"]] = art
        except json.JSONDecodeError:
            pass

print(f"\nTotal abstracts now accessible: {len(abstracts_by_pmid)}")

# Rebuild gold_standard_to_annotate.tsv with correct PMIDs
print("\nRebuilding to-annotate file...")
gold_annot_pmids = {}
with open(ANNOTATIONS, encoding="utf-8") as f:
    for r in csv.DictReader(f, delimiter="\t"):
        if r["annot_id"] not in gold_annot_pmids:
            gold_annot_pmids[r["annot_id"]] = r["pmid"]

with open(SOURCE_OLD, encoding="utf-8") as f:
    reader = csv.DictReader(f, delimiter="\t")
    fieldnames = reader.fieldnames
    existing = {r["annot_id"]: r for r in reader}

fixed_rows = []
fixed_count = 0
still_missing = []
for aid in sorted(existing.keys()):
    if aid not in gold_annot_pmids:
        fixed_rows.append(existing[aid])
        continue

    gold_pmid = gold_annot_pmids[aid]
    if existing[aid]["pmid"] == gold_pmid:
        fixed_rows.append(existing[aid])
        continue

    if gold_pmid not in abstracts_by_pmid:
        still_missing.append((aid, gold_pmid))
        fixed_rows.append(existing[aid])
        continue

    art = abstracts_by_pmid[gold_pmid]
    fixed_rows.append({
        "annot_id": aid,
        "stratum": classify(art),
        "pmid": gold_pmid,
        "year": art.get("year", ""),
        "journal": art.get("journal", ""),
        "title": art.get("title", ""),
        "abstract": art.get("abstract", ""),
        "doi": art.get("doi", ""),
        "publication_types": "|".join(art.get("publication_types", [])),
        "mesh_terms": "|".join(art.get("mesh_terms", [])[:10]),
    })
    fixed_count += 1

print(f"Fixed {fixed_count} rows")
if still_missing:
    print(f"Still couldn't fix {len(still_missing)}:")
    for aid, pmid in still_missing:
        print(f"  {aid}: PMID {pmid}")

with open(SOURCE_NEW, "w", encoding="utf-8", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t",
                            quoting=csv.QUOTE_MINIMAL)
    writer.writeheader()
    for r in fixed_rows:
        clean = {c: (r.get(c) or "") for c in fieldnames}
        writer.writerow(clean)

print(f"\nWrote fixed file to: {SOURCE_NEW}")
print(f"Verify with: head -5 {SOURCE_NEW}")
print(f"Then replace original: mv {SOURCE_NEW} {SOURCE_OLD}")
