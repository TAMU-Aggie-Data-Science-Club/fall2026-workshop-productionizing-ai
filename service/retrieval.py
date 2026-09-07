"""Course-note retrieval: one dot product against a prebuilt matrix.

No vector database. The index is a few hundred rows of 384 floats -- well under
a megabyte -- so brute-force cosine similarity is microseconds. A vector DB here
would add a service to run, a port to bind and a new way for the workshop to
fail, in exchange for nothing.
"""
import pathlib

import numpy as np

from embed import embed_one

INDEX = pathlib.Path(__file__).resolve().parents[1] / "data" / "index.npz"

with np.load(INDEX, allow_pickle=False) as _data:
    _vectors: np.ndarray = _data["vectors"]
    _texts: list[str] = list(_data["texts"])


def search(question: str, k: int) -> list[str]:
    """Return the k most similar note chunks. Vectors are already normalised."""
    return [item["text"] for item in search_details(question, k)]


def search_details(question: str, k: int) -> list[dict]:
    """Return note chunks plus safe, user-visible retrieval metadata.

    The browser uses this to explain which course notes grounded an answer.
    It intentionally returns excerpts and similarity scores, not the prompt or
    model's private reasoning.
    """
    if k <= 0:
        return []
    scores = _vectors @ embed_one(question)
    top = np.argsort(-scores)[:k]
    results = []
    for i in top:
        text = str(_texts[i])
        source, separator, content = text.partition("] ")
        source = source.lstrip("[") if separator else "course notes"
        title, separator, excerpt = content.partition(": ")
        if not separator:
            title, excerpt = "Course notes", content
        results.append({
            "text": text,
            "source": source,
            "title": title,
            "excerpt": excerpt[:180].rstrip() + ("…" if len(excerpt) > 180 else ""),
            "score": round(float(scores[i]), 3),
        })
    return results


def size() -> int:
    return len(_texts)
