"""Resolve near-duplicate candidate pairs against reference ontologies.

Reviewer point 2 ("semantic linking"): for each candidate pair in
review_candidates.csv, resolve both member labels against the authoritative
vocabulary for their entity type and decide MERGE / KEEP / MANUAL.

  Microbe     -> NCBI Taxonomy   (E-utilities esearch + esummary)
  Bioactive   -> ChEBI           (EBI OLS4)
  IBD_Outcome -> MONDO           (EBI OLS4)
  Food        -> FoodOn          (EBI OLS4)

Decision rule (conservative, to avoid false merges):
  both labels resolve (exact/synonym) to the SAME canonical id  -> MERGE
  both resolve to DIFFERENT canonical ids                       -> KEEP
  either side does not resolve by an exact match                -> MANUAL

Writes review_candidates_resolved.csv with the resolved ids + evidence.

Needs outbound access to eutils.ncbi.nlm.nih.gov and www.ebi.ac.uk.
Optional env vars: NCBI_API_KEY (raises rate limit 3->10 rps), NCBI_EMAIL.
Run a network-free routing check first with:  python resolve_candidates.py --dry-run
"""
import argparse
import csv
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from functools import lru_cache

NCBI_KEY = os.environ.get("NCBI_API_KEY", "")
NCBI_EMAIL = os.environ.get("NCBI_EMAIL", "anonymous@example.com")
NCBI_DELAY = 0.11 if NCBI_KEY else 0.34
OLS_DELAY = 0.05
OLS_ONTO = {"Bioactive": "chebi", "IBD_Outcome": "mondo", "Food": "foodon"}
NCBI_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
OLS_BASE = "https://www.ebi.ac.uk/ols4/api/search"


def _get_json(url, tries=4):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "DietIBD-KG/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception as e:                       # noqa
            last = e
            time.sleep(1.5 * (i + 1))
    raise last


@lru_cache(maxsize=8192)
def resolve_ncbi(name):
    """NCBI Taxonomy. Returns dict(id, name, rank, count) or None."""
    key = f"&api_key={NCBI_KEY}" if NCBI_KEY else ""
    q = urllib.parse.quote(name)
    time.sleep(NCBI_DELAY)
    d = _get_json(f"{NCBI_BASE}/esearch.fcgi?db=taxonomy&term={q}"
                  f"&retmode=json&tool=dietibdkg&email={NCBI_EMAIL}{key}")
    res = d.get("esearchresult", {})
    ids = res.get("idlist", [])
    if not ids:
        return None
    taxid = ids[0]
    time.sleep(NCBI_DELAY)
    s = _get_json(f"{NCBI_BASE}/esummary.fcgi?db=taxonomy&id={taxid}"
                  f"&retmode=json&tool=dietibdkg&email={NCBI_EMAIL}{key}")
    rec = s.get("result", {}).get(taxid, {})
    return {"id": f"NCBITaxon:{taxid}",
            "name": rec.get("scientificname", ""),
            "rank": rec.get("rank", ""),
            "count": int(res.get("count", "1") or 1)}


@lru_cache(maxsize=8192)
def resolve_ols(name, onto):
    """ChEBI/MONDO/FoodOn via OLS4. Returns dict(id, name, exact) or None.

    Tries an exact (label/synonym) match first; falls back to the best fuzzy
    hit flagged exact=False so the decision logic can route it to MANUAL.
    """
    q = urllib.parse.quote(name)
    for exact in ("true", "false"):
        time.sleep(OLS_DELAY)
        d = _get_json(f"{OLS_BASE}?q={q}&ontology={onto}&exact={exact}&rows=5")
        docs = d.get("response", {}).get("docs", [])
        if docs:
            top = docs[0]
            cid = top.get("obo_id") or top.get("short_form") or top.get("iri")
            return {"id": cid, "name": top.get("label", ""), "exact": exact == "true"}
    return None


def decide(a, b, exact_required):
    """Return (decision, note) from two resolution results."""
    if a is None and b is None:
        return "MANUAL", "neither label resolved in ontology"
    if a is None or b is None:
        side = "label_a" if a is None else "label_b"
        return "MANUAL", f"{side} did not resolve (likely typo / non-ontology term)"
    if exact_required and not (a.get("exact") and b.get("exact")):
        return "MANUAL", "resolved only by fuzzy match; needs human check"
    if a["id"] == b["id"]:
        return "MERGE", f"both -> {a['id']} ({a['name']})"
    return "KEEP", f"distinct: {a['id']} ({a.get('rank', a['name'])}) vs {b['id']} ({b.get('rank', b['name'])})"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="infile", default="review_candidates.csv")
    ap.add_argument("--out", dest="outfile", default="review_candidates_resolved.csv")
    ap.add_argument("--dry-run", action="store_true",
                    help="route pairs and report counts without any network calls")
    args = ap.parse_args()

    with open(args.infile, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    print(f"{len(rows)} candidate pairs")
    routing = {}
    for r in rows:
        et = r["entity_type"]
        routing[et] = routing.get(et, 0) + 1
    print("routing:", {et: ("NCBI Taxonomy" if et == "Microbe" else f"OLS:{OLS_ONTO.get(et,'?')}")
                        + f" x{n}" for et, n in routing.items()})
    if args.dry_run:
        print("dry run -- no network calls made. Re-run without --dry-run to resolve.")
        return

    out, tally = [], {"MERGE": 0, "KEEP": 0, "MANUAL": 0}
    for i, r in enumerate(rows, 1):
        et = r["entity_type"]
        if et == "Microbe":
            a, b = resolve_ncbi(r["label_a"]), resolve_ncbi(r["label_b"])
            decision, note = decide(a, b, exact_required=False)
        else:
            onto = OLS_ONTO.get(et)
            a = resolve_ols(r["label_a"], onto) if onto else None
            b = resolve_ols(r["label_b"], onto) if onto else None
            decision, note = decide(a, b, exact_required=True)
        tally[decision] += 1
        out.append({
            **r,
            "canon_a": (a or {}).get("id", ""), "canon_a_name": (a or {}).get("name", ""),
            "canon_b": (b or {}).get("id", ""), "canon_b_name": (b or {}).get("name", ""),
            "decision": decision, "note": note,
        })
        if i % 20 == 0 or i == len(rows):
            print(f"  {i}/{len(rows)}  running tally {tally}")

    cols = (list(rows[0].keys()) +
            ["canon_a", "canon_a_name", "canon_b", "canon_b_name", "decision", "note"])
    with open(args.outfile, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(out)

    print(f"\nwrote {args.outfile}")
    print("final:", tally)
    for et in routing:
        sub = [o for o in out if o["entity_type"] == et]
        t = {d: sum(1 for o in sub if o["decision"] == d) for d in ("MERGE", "KEEP", "MANUAL")}
        print(f"  {et}: {t}")


if __name__ == "__main__":
    main()
