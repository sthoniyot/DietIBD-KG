"""Objective 1: Train KG embeddings and evaluate link prediction.

Trains TransE, DistMult, and RotatE on the DietIBD-KG triples using PyKEEN.
All three models use an identical training configuration (self-adversarial
negative sampling, sLCWA) so the comparison reflects model architecture
rather than tuning differences.

Note: ComplEx was originally planned but exhibited unstable training on this
KG across multiple configurations; DistMult is reported as the
semantic-matching baseline in its place.

Outputs:
  - data/processed/embeddings/<model>/ : trained model + artifacts per model
  - data/processed/embeddings/embedding_results.json : raw metrics
  - docs/objective1_embeddings_results.md : results report

Usage:
    python src/analysis/train_embeddings.py
"""
import json
from datetime import datetime
from pathlib import Path

import torch
from pykeen.pipeline import pipeline
from pykeen.triples import TriplesFactory

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EMB_DIR = PROJECT_ROOT / "data" / "processed" / "embeddings"
TRIPLES_FILE = EMB_DIR / "kg_triples.tsv"
RESULTS_MD = PROJECT_ROOT / "docs" / "objective1_embeddings_results.md"
RESULTS_JSON = EMB_DIR / "embedding_results.json"

MODELS = ["TransE", "DistMult", "RotatE"]
EMBEDDING_DIM = 256
NUM_EPOCHS = 200
NUM_NEGS = 50
LEARNING_RATE = 0.001
BATCH_SIZE = 512
SEED = 42

# Unified training configuration — identical for all three models
COMMON_CONFIG = dict(
    training_loop="slcwa",
    loss="NSSALoss",
    loss_kwargs=dict(margin=9.0, adversarial_temperature=1.0),
    negative_sampler="basic",
    negative_sampler_kwargs=dict(num_negs_per_pos=NUM_NEGS),
    optimizer="Adam",
    optimizer_kwargs=dict(lr=LEARNING_RATE),
)


def main():
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Device: {device}")

    print(f"\nLoading triples from {TRIPLES_FILE}...")
    tf = TriplesFactory.from_path(str(TRIPLES_FILE))
    print(f"  {tf.num_triples:,} triples, {tf.num_entities:,} entities, "
          f"{tf.num_relations} relations")

    train, test, valid = tf.split([0.8, 0.1, 0.1], random_state=SEED)
    print(f"  Split: {train.num_triples:,} train / {test.num_triples:,} test / "
          f"{valid.num_triples:,} valid")

    results = {}
    for model_name in MODELS:
        print(f"\n{'='*55}")
        print(f"Training {model_name} "
              f"(dim={EMBEDDING_DIM}, epochs={NUM_EPOCHS}, negs={NUM_NEGS})")
        print('='*55)
        result = pipeline(
            training=train,
            testing=test,
            validation=valid,
            model=model_name,
            model_kwargs=dict(embedding_dim=EMBEDDING_DIM),
            training_kwargs=dict(num_epochs=NUM_EPOCHS, batch_size=BATCH_SIZE),
            random_seed=SEED,
            device=device,
            **COMMON_CONFIG,
        )
        metrics = {
            "MRR": float(result.get_metric("mrr")),
            "Hits@1": float(result.get_metric("hits@1")),
            "Hits@3": float(result.get_metric("hits@3")),
            "Hits@10": float(result.get_metric("hits@10")),
            "MeanRank": float(result.get_metric("mean_rank")),
        }
        results[model_name] = metrics

        model_dir = EMB_DIR / model_name.lower()
        result.save_to_directory(str(model_dir))

        print(f"\n  {model_name} link-prediction results:")
        for k, v in metrics.items():
            print(f"    {k:10s}: {v:.4f}")
        print(f"  Model saved to {model_dir}")

    best = max(results, key=lambda m: results[m]["MRR"])

    # ── Write results report ──
    lines = [
        "# DietIBD-KG — Objective 1 Embedding Results",
        "",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "## Setup",
        "",
        f"- Triples: {tf.num_triples:,} "
        f"({train.num_triples:,} train / {test.num_triples:,} test / "
        f"{valid.num_triples:,} valid), 80/10/10 split",
        f"- Entities: {tf.num_entities:,}  |  Relations: {tf.num_relations}",
        f"- Embedding dimension: {EMBEDDING_DIM}  |  Epochs: {NUM_EPOCHS}",
        f"- Random seed: {SEED}  |  Library: PyKEEN  |  Device: {device}",
        "",
        "All three models were trained with an identical configuration for a "
        "fair architecture comparison: sLCWA training, self-adversarial "
        f"negative sampling loss (NSSALoss; margin 9.0, adversarial "
        f"temperature 1.0), {NUM_NEGS} negatives per positive, Adam optimizer "
        f"(lr {LEARNING_RATE}).",
        "",
        "Note: ComplEx was originally planned as the semantic-matching "
        "baseline but exhibited unstable training on this KG across multiple "
        "configurations; DistMult is reported in its place.",
        "",
        "## Link Prediction Results",
        "",
        "| Model | MRR | Hits@1 | Hits@3 | Hits@10 | Mean Rank |",
        "|---|---|---|---|---|---|",
    ]
    for m in MODELS:
        r = results[m]
        lines.append(
            f"| {m} | {r['MRR']:.4f} | {r['Hits@1']:.4f} | {r['Hits@3']:.4f} "
            f"| {r['Hits@10']:.4f} | {r['MeanRank']:.1f} |"
        )
    lines += [
        "",
        f"**Best model by MRR: {best} (MRR = {results[best]['MRR']:.4f}, "
        f"Hits@10 = {results[best]['Hits@10']:.4f})**",
        "",
        "## Interpretation",
        "",
        "MRR (mean reciprocal rank) and Hits@k measure how well each model "
        "ranks held-out true edges against corrupted alternatives; higher is "
        "better. RotatE is expected to lead, as its rotational relation "
        "embeddings capture the directional and compositional relation "
        "patterns present in the KG; DistMult, restricted to symmetric "
        "relations, provides a lower-bound semantic-matching baseline. These "
        "results establish the baseline relation-prediction capability of the "
        "DietIBD-KG and provide entity embeddings for downstream objectives.",
        "",
    ]
    RESULTS_MD.write_text("\n".join(lines), encoding="utf-8")
    RESULTS_JSON.write_text(json.dumps(results, indent=2), encoding="utf-8")

    print(f"\n{'='*55}")
    print(f"Best model by MRR: {best}")
    print(f"Report:  {RESULTS_MD}")
    print(f"Metrics: {RESULTS_JSON}")


if __name__ == "__main__":
    main()
