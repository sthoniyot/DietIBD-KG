"""NCBI Taxonomy loader and search.

Loads names.dmp (~3M+ entries) and nodes.dmp (~2.6M+ entries) from a downloaded
taxdump archive. Builds an index for fast lookup by name with cascaded matching.

Format note:
    NCBI .dmp files use the delimiter '\t|\t' between fields and '\t|' at end of line.
    Example names.dmp line:
        "562\t|\tEscherichia coli\t|\t\t|\tscientific name\t|"
"""
import pickle
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import ONTOLOGY_DATA

NCBI_DIR = ONTOLOGY_DATA / "ncbi_taxonomy"
NAMES_DMP = NCBI_DIR / "names.dmp"
NODES_DMP = NCBI_DIR / "nodes.dmp"
CACHE_DIR = ONTOLOGY_DATA / "cache"
CACHE_FILE = CACHE_DIR / "ncbi_taxonomy.pkl"

# Name classes we prefer for canonical name (in order)
NAME_CLASS_PRIORITY = [
    "scientific name",
    "synonym",
    "equivalent name",
    "genbank synonym",
    "common name",
    "blast name",
]


def parse_dmp_line(line):
    """Parse one .dmp file line into list of stripped fields."""
    line = line.rstrip("\n").rstrip("\t|")
    return [f.strip() for f in line.split("\t|\t")]


def parse_names_dmp(filepath):
    """Parse names.dmp and return:
       - tax_to_names: {tax_id: {name_class: [names]}}
       - name_to_tax:  {name_lower: [(tax_id, name_class)]}
    """
    tax_to_names = {}
    name_to_tax = {}

    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            fields = parse_dmp_line(line)
            if len(fields) < 4:
                continue
            tax_id, name, _unique_name, name_class = fields[:4]

            tax_to_names.setdefault(tax_id, {}).setdefault(name_class, []).append(name)
            name_lower = name.lower()
            name_to_tax.setdefault(name_lower, []).append((tax_id, name_class))

    return tax_to_names, name_to_tax


def parse_nodes_dmp(filepath):
    """Parse nodes.dmp and return:
       - tax_to_rank:   {tax_id: rank}
       - tax_to_parent: {tax_id: parent_id}
    """
    tax_to_rank = {}
    tax_to_parent = {}

    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            fields = parse_dmp_line(line)
            if len(fields) < 3:
                continue
            tax_id, parent_id, rank = fields[:3]
            tax_to_rank[tax_id] = rank
            tax_to_parent[tax_id] = parent_id

    return tax_to_rank, tax_to_parent


def build_cache():
    """Build the pickled cache. Run once after downloading taxdump."""
    if not NAMES_DMP.exists():
        raise FileNotFoundError(
            f"names.dmp not found at {NAMES_DMP}. "
            f"Download taxdump.tar.gz from NCBI first."
        )

    print("Parsing names.dmp ... (~30s, large file)")
    tax_to_names, name_to_tax = parse_names_dmp(NAMES_DMP)
    print(f"  {len(tax_to_names):,} unique taxa, {len(name_to_tax):,} unique name strings")

    print("Parsing nodes.dmp ...")
    tax_to_rank, tax_to_parent = parse_nodes_dmp(NODES_DMP)
    print(f"  {len(tax_to_rank):,} taxa with rank info")

    CACHE_DIR.mkdir(exist_ok=True)
    cache = {
        "tax_to_names": tax_to_names,
        "name_to_tax": name_to_tax,
        "tax_to_rank": tax_to_rank,
        "tax_to_parent": tax_to_parent,
    }

    print(f"Writing cache to {CACHE_FILE} ...")
    with open(CACHE_FILE, "wb") as f:
        pickle.dump(cache, f, protocol=pickle.HIGHEST_PROTOCOL)
    size_mb = CACHE_FILE.stat().st_size / 1e6
    print(f"  Cache size: {size_mb:.1f} MB")
    return cache


def load_cache():
    """Load the pickled cache. Builds it first if missing."""
    if not CACHE_FILE.exists():
        return build_cache()
    with open(CACHE_FILE, "rb") as f:
        return pickle.load(f)


def get_canonical_name(tax_id, tax_to_names):
    """Return the scientific name for a tax_id (or first available name)."""
    if tax_id not in tax_to_names:
        return None
    names = tax_to_names[tax_id]
    for name_class in NAME_CLASS_PRIORITY:
        if name_class in names:
            return names[name_class][0]
    for name_list in names.values():
        if name_list:
            return name_list[0]
    return None


def search_microbe(query, cache=None, max_results=5):
    """Cascaded search for a microbe name.

    Match priority:
        1. exact_scientific - query is the scientific name of the taxon
        2. exact_synonym    - query matches a synonym/equivalent name exactly
        3. exact_anyname    - query matches any name class exactly
        4. substring        - query appears in a scientific name (last resort)

    Returns list of (tax_id, canonical_name, rank, match_type).
    """
    if cache is None:
        cache = load_cache()

    tax_to_names = cache["tax_to_names"]
    name_to_tax = cache["name_to_tax"]
    tax_to_rank = cache["tax_to_rank"]

    query_lower = query.lower().strip()
    seen = set()
    results_by_priority = {1: [], 2: [], 3: [], 4: []}

    if query_lower in name_to_tax:
        for tax_id, name_class in name_to_tax[query_lower]:
            if tax_id in seen:
                continue
            seen.add(tax_id)
            canonical = get_canonical_name(tax_id, tax_to_names)
            rank = tax_to_rank.get(tax_id, "no rank")
            if name_class == "scientific name":
                results_by_priority[1].append((tax_id, canonical, rank, "exact_scientific"))
            elif name_class in ("synonym", "equivalent name", "genbank synonym"):
                results_by_priority[2].append((tax_id, canonical, rank, "exact_synonym"))
            else:
                results_by_priority[3].append((tax_id, canonical, rank, "exact_anyname"))

    has_results = sum(len(v) for v in results_by_priority.values()) > 0
    if not has_results:
        substr_count = 0
        for name_lower, taxa in name_to_tax.items():
            if query_lower in name_lower and substr_count < max_results * 3:
                for tax_id, name_class in taxa:
                    if name_class != "scientific name" or tax_id in seen:
                        continue
                    seen.add(tax_id)
                    canonical = get_canonical_name(tax_id, tax_to_names)
                    rank = tax_to_rank.get(tax_id, "no rank")
                    results_by_priority[4].append((tax_id, canonical, rank, "substring"))
                    substr_count += 1
                    if substr_count >= max_results * 3:
                        break

    ordered = []
    for tier in sorted(results_by_priority.keys()):
        ordered.extend(results_by_priority[tier])
        if len(ordered) >= max_results:
            break
    return ordered[:max_results]


if __name__ == "__main__":
    print("Loading NCBI Taxonomy cache (will build if not present) ...")
    cache = load_cache()
    print(f"  {len(cache['tax_to_names']):,} taxa loaded\n")

    test_microbes = [
        "Faecalibacterium prausnitzii",
        "Akkermansia muciniphila",
        "Bacteroides fragilis",
        "Escherichia coli",
        "Lactobacillus rhamnosus",
        "Roseburia intestinalis",
        "Bifidobacterium",
        "Ruminococcaceae",
    ]

    print(f"{'Query':<35} {'Tax ID':<10} {'Rank':<10} {'Canonical name':<40} Match")
    print("-" * 115)
    for query in test_microbes:
        results = search_microbe(query, cache, max_results=2)
        if not results:
            print(f"  X {query:<33} (not found)")
            continue
        for i, (tax_id, name, rank, match_type) in enumerate(results):
            marker = "+" if match_type == "exact_scientific" else "?"
            prefix = f"  {marker} {query:<33}" if i == 0 else f"    {'':<33}"
            print(f"{prefix} {tax_id:<10} {rank:<10} {name:<40} {match_type}")
