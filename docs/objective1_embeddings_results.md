# DietIBD-KG — Objective 1 Embedding Results

Generated: 2026-05-21 16:01

## Setup

- Triples: 14,850 (11,880 train / 1,485 test / 1,485 valid), 80/10/10 split
- Entities: 4,603  |  Relations: 12
- Embedding dimension: 256  |  Epochs: 200
- Random seed: 42  |  Library: PyKEEN  |  Device: cuda

All three models were trained with an identical configuration for a fair architecture comparison: sLCWA training, self-adversarial negative sampling loss (NSSALoss; margin 9.0, adversarial temperature 1.0), 50 negatives per positive, Adam optimizer (lr 0.001).

Note: ComplEx was originally planned as the semantic-matching baseline but exhibited unstable training on this KG across multiple configurations; DistMult is reported in its place.

## Link Prediction Results

| Model | MRR | Hits@1 | Hits@3 | Hits@10 | Mean Rank |
|---|---|---|---|---|---|
| TransE | 0.4468 | 0.3444 | 0.5061 | 0.6286 | 133.3 |
| DistMult | 0.1883 | 0.1488 | 0.2061 | 0.2269 | 1098.5 |
| RotatE | 0.4935 | 0.4104 | 0.5512 | 0.6330 | 198.8 |

**Best model by MRR: RotatE (MRR = 0.4935, Hits@10 = 0.6330)**

## Interpretation

MRR (mean reciprocal rank) and Hits@k measure how well each model ranks held-out true edges against corrupted alternatives; higher is better. RotatE is expected to lead, as its rotational relation embeddings capture the directional and compositional relation patterns present in the KG; DistMult, restricted to symmetric relations, provides a lower-bound semantic-matching baseline. These results establish the baseline relation-prediction capability of the DietIBD-KG and provide entity embeddings for downstream objectives.
