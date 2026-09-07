"""Generate the frozen question corpus.

Duplicates are DELIBERATE: during finals week many students ask the same thing
in the same words, and a few ask it in different words. That mix is what gives
the cache levers something real to hit.

The corpus is built from a REPEATING TEMPLATE rather than by random sampling,
because the duplicate structure has to survive truncation. The benchmark sends
the first N questions; if repeats were merely sprinkled across all 60 rows, a
16-request run would contain almost none and caching would look useless.
Cycling a fixed pattern guarantees the same mix at every prefix length.
"""
import json
from collections import Counter

# Small hot pool -- the questions everybody asks during finals.
BASE = [
    "What is Big-O notation?",
    "What does the learning rate do?",
    "What is overfitting?",
    "When are office hours?",
    "What is cross-validation?",
]

# Same meaning, different words: exact cache MISSES, semantic cache HITS.
NEAR = [
    "What is the role of the learning rate?",
    "What does it mean for a model to overfit?",
    "What time are office hours held?",
    "Can you explain k-fold cross validation?",
]

# The long tail: asked once, never again.
TAIL = [
    "Define recursion.", "Define variance.", "What is a p-value?",
    "Explain the LEGB scope rule in Python.",
    "What is the difference between a stack and a queue?",
    "What sorting algorithm does Python use?",
    "How do I get an extension on an assignment?",
    "What is feature scaling and when do I need it?",
    "How long is the midterm?", "What is the normal distribution?",
    "What happens if I submit an assignment late?",
    "What is a confidence interval?",
    "Why do we split data into train, validation and test sets?",
    "What is L1 regularisation?", "What is a confusion matrix?",
    "How does binary search work?",
]

# 10-slot pattern: 6 base (repeats), 2 near (semantic hits), 2 tail (misses).
PATTERN = ["B", "B", "T", "B", "N", "B", "T", "B", "N", "B"]

TOTAL = 60
rows, bi, ni, ti = [], 0, 0, 0
for i in range(TOTAL):
    slot = PATTERN[i % len(PATTERN)]
    if slot == "B":
        rows.append({"question": BASE[bi % len(BASE)], "kind": "base"}); bi += 1
    elif slot == "N":
        rows.append({"question": NEAR[ni % len(NEAR)], "kind": "near"}); ni += 1
    else:
        rows.append({"question": TAIL[ti % len(TAIL)], "kind": "tail"}); ti += 1

with open("benchmark/prompts.jsonl", "w") as f:
    for r in rows:
        f.write(json.dumps(r) + "\n")

print(f"{TOTAL} rows:", dict(Counter(r["kind"] for r in rows)))
for n in (16, 24, 32, 60):
    prefix = [r["question"] for r in rows[:n]]
    print(f"  first {n:2d}: {len(set(prefix)):2d} distinct -> "
          f"{(n-len(set(prefix)))/n*100:.0f}% exact repeats available")
