# DietIBD-KG — Objective 1 Embedding Results (v1.2.0)

Generated: 2026-05-27 22:08

## Setup

- Triples: 14,818 (11,854 train / 1,482 test / 1,482 valid), 80/10/10 split
- Entities: 4,539  |  Relations: 12
- Embedding dimension: 256  |  Epochs: 200
- Random seed: 42  |  Library: PyKEEN  |  Device: cuda

All three models were trained with an identical configuration for a fair architecture comparison: sLCWA training, self-adversarial negative sampling loss (NSSALoss; margin 9.0, adversarial temperature 1.0), 50 negatives per positive, Adam optimizer (lr 0.001).

Note: ComplEx was originally planned as the semantic-matching baseline but exhibited unstable training on this KG across multiple configurations; DistMult is reported in its place.

## Link Prediction Results

| Model | MRR | Hits@1 | Hits@3 | Hits@10 | Mean Rank |
|---|---|---|---|---|---|
| TransE | 0.4572 | 0.3657 | 0.5091 | 0.6279 | 129.7 |
| DistMult | 0.2092 | 0.1741 | 0.2210 | 0.2460 | 1064.9 |
| RotatE | 0.5130 | 0.4379 | 0.5631 | 0.6424 | 196.4 |

**Best model by MRR: RotatE (MRR = 0.5130, Hits@10 = 0.6424)**

## Interpretation

MRR (mean reciprocal rank) and Hits@k measure how well each model ranks held-out true edges against corrupted alternatives; higher is better. RotatE is expected to lead, as its rotational relation embeddings capture the directional and compositional relation patterns present in the KG; DistMult, restricted to symmetric relations, provides a lower-bound semantic-matching baseline. These results establish the baseline relation-prediction capability of the DietIBD-KG and provide entity embeddings for downstream objectives.
