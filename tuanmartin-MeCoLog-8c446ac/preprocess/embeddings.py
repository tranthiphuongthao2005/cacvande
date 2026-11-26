"""Compute frozen 768-dimensional template vectors from a local SBERT snapshot."""

import numpy as np

MODEL_ID = "sentence-transformers/distilbert-base-nli-mean-tokens"
DIM = 768


def embed_templates(templates, model_dir, batch_size):
    from sentence_transformers import SentenceTransformer

    if not model_dir.is_dir():
        raise ValueError(f"Expected a local snapshot of {MODEL_ID}: {model_dir}")
    model = SentenceTransformer(str(model_dir.resolve()), device="cpu", local_files_only=True)
    model.eval()
    model.requires_grad_(False)
    backbone = getattr(model[0], "auto_model", None)
    pooling = model[1] if len(model) > 1 else None
    if (getattr(getattr(backbone, "config", None), "model_type", None) != "distilbert"
            or getattr(pooling, "pooling_mode_mean_tokens", False) is not True
            or model.get_sentence_embedding_dimension() != DIM):
        raise ValueError(f"Expected the local DistilBERT SBERT snapshot with {DIM}-dimensional mean pooling")
    unique = sorted(set(templates))
    cache = {}
    for start in range(0, len(unique), batch_size):
        batch = unique[start:start + batch_size]
        vectors = model.encode(batch, batch_size=batch_size, convert_to_numpy=True, show_progress_bar=False)
        if vectors.shape != (len(batch), DIM) or not np.isfinite(vectors).all():
            raise ValueError("Invalid SBERT vectors")
        cache.update(zip(batch, vectors.astype(np.float32, copy=False)))
    return cache
