"""Embedding access for the DietIBD-KG (RotatE by default)."""
from __future__ import annotations

import numpy as np

from dietibdkg import config


class Embeddings:
    """Access to trained KG entity embeddings.

    Requires the optional 'embeddings' dependencies and a trained model
    under data/processed/embeddings/<model>/ (produced by
    src/analysis/train_embeddings.py).

    Example:
        >>> from dietibdkg import Embeddings
        >>> emb = Embeddings("rotate")
        >>> vec = emb.get_vector("resveratrol")
        >>> emb.most_similar("resveratrol", k=5)
    """

    def __init__(self, model=None):
        try:
            import torch
            from pykeen.triples import TriplesFactory
        except ImportError as e:
            raise ImportError(
                "Embedding support requires PyKEEN and PyTorch. "
                "Install with:  pip install -e '.[embeddings]'"
            ) from e

        model = model or config.DEFAULT_EMBEDDING_MODEL
        model_path = config.EMBEDDINGS_DIR / model / "trained_model.pkl"
        if not model_path.exists():
            raise FileNotFoundError(
                f"No trained model at {model_path}. "
                f"Run src/analysis/train_embeddings.py first."
            )

        self.model_name = model
        self._model = torch.load(model_path, weights_only=False,
                                 map_location="cpu")
        self._tf = TriplesFactory.from_path(str(config.TRIPLES_FILE))
        self._entity_to_id = self._tf.entity_to_id
        self._id_to_entity = {v: k for k, v in self._entity_to_id.items()}

        # Real-valued embedding matrix (complex models -> [real | imag])
        emb = self._model.entity_representations[0]().detach().cpu()
        if torch.is_complex(emb):
            emb = torch.cat([emb.real, emb.imag], dim=-1)
        self._matrix = emb.numpy()
        self._kg = None  # lazy KG handle for label lookup

    def _resolve(self, entity):
        """Accept an entity id, or fall back to a KG label lookup."""
        if entity in self._entity_to_id:
            return entity
        from dietibdkg.kg import KnowledgeGraph
        if self._kg is None:
            self._kg = KnowledgeGraph()
        ent = self._kg.get_entity(entity)
        if ent and ent["id"] in self._entity_to_id:
            return ent["id"]
        raise KeyError(f"Entity not in embedding space: {entity!r}")

    def get_vector(self, entity):
        """Return the real-valued embedding vector for an entity."""
        eid = self._resolve(entity)
        return self._matrix[self._entity_to_id[eid]].copy()

    def most_similar(self, entity, k=10):
        """Return the k most similar entities by cosine similarity."""
        eid = self._resolve(entity)
        idx = self._entity_to_id[eid]
        v = self._matrix[idx]
        denom = np.linalg.norm(self._matrix, axis=1) * np.linalg.norm(v) + 1e-12
        sims = (self._matrix @ v) / denom
        out = []
        for i in np.argsort(-sims):
            if i == idx:
                continue
            out.append({"id": self._id_to_entity[i],
                        "similarity": float(sims[i])})
            if len(out) >= k:
                break
        return out

    @property
    def num_entities(self):
        return self._matrix.shape[0]

    @property
    def dimension(self):
        return self._matrix.shape[1]
