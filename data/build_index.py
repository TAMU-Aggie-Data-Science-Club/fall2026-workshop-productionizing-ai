"""Chunk the course notes, embed them, and save a single .npz index.

Run once at image build time -- never at request time. The result is a matrix
small enough (a few hundred rows) that cosine similarity with one numpy dot
product beats any vector database, with no server to run and nothing to break
on the day.
"""
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "service"))
from embed import embed_texts  # noqa: E402

NOTES_DIR = pathlib.Path(__file__).parent / "course_notes"
OUT = pathlib.Path(__file__).parent / "index.npz"


def chunk(markdown: str, source: str) -> list[str]:
    """One chunk per '##' section -- they are already topic-sized."""
    chunks = []
    current_title, current_body = None, []
    for line in markdown.splitlines():
        if line.startswith("## "):
            if current_title:
                chunks.append(f"{current_title}: {' '.join(current_body).strip()}")
            current_title, current_body = line[3:].strip(), []
        elif line.startswith("# "):
            continue
        elif line.strip():
            current_body.append(line.strip())
    if current_title:
        chunks.append(f"{current_title}: {' '.join(current_body).strip()}")
    return [f"[{source}] {c}" for c in chunks if len(c) > 40]


def main() -> None:
    texts: list[str] = []
    for path in sorted(NOTES_DIR.glob("*.md")):
        texts.extend(chunk(path.read_text(), path.stem))
    print(f"{len(texts)} chunks from {len(list(NOTES_DIR.glob('*.md')))} files")

    vectors = embed_texts(texts)
    # Keep texts as a normal Unicode array so serving can load the artifact
    # with allow_pickle=False. The index contains strings, not Python objects.
    np.savez_compressed(OUT, vectors=vectors, texts=np.array(texts))
    print(f"wrote {OUT}  vectors={vectors.shape}")


if __name__ == "__main__":
    main()
