"""One small embedding model, shared by retrieval and the semantic cache.

Loaded once at import. Using transformers directly with mean pooling avoids a
heavier dependency for what is ultimately twenty lines of code.
"""
import os

import numpy as np
import torch
from transformers import AutoModel, AutoTokenizer

MODEL = "sentence-transformers/all-MiniLM-L6-v2"
LOCAL_ONLY = os.environ.get("NIMBUS_ALLOW_MODEL_DOWNLOAD") != "1"

# Serving must never make a surprise network call. `prefetch.py` and the index
# build opt in to downloads explicitly; every normal request uses the local
# cache and fails fast with an actionable error if preflight was skipped.
_tokenizer = None
_model = None


def _ensure_loaded():
    """Load lazily, and fail with a sentence rather than a huggingface traceback."""
    global _tokenizer, _model
    if _model is None:
        try:
            _tokenizer = AutoTokenizer.from_pretrained(MODEL, local_files_only=LOCAL_ONLY)
            _model = AutoModel.from_pretrained(MODEL, local_files_only=LOCAL_ONLY)
            _model.eval()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"\n\n  Embedding model '{MODEL}' is not downloaded yet.\n"
                f"  Run this once, then try again:\n\n"
                f"      .venv/bin/python .devcontainer/prefetch.py\n\n"
                f"  (original error: {type(exc).__name__})\n") from exc


def embed_texts(texts: list[str]) -> np.ndarray:
    """Return L2-normalised embeddings, so cosine similarity is just a dot product."""
    _ensure_loaded()
    out = []
    for i in range(0, len(texts), 32):
        batch = texts[i : i + 32]
        encoded = _tokenizer(batch, padding=True, truncation=True,
                             max_length=256, return_tensors="pt")
        with torch.no_grad():
            hidden = _model(**encoded).last_hidden_state
        mask = encoded["attention_mask"].unsqueeze(-1).float()
        pooled = (hidden * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
        pooled = torch.nn.functional.normalize(pooled, p=2, dim=1)
        out.append(pooled.numpy().astype(np.float32))
    return np.vstack(out)


def embed_one(text: str) -> np.ndarray:
    return embed_texts([text])[0]
