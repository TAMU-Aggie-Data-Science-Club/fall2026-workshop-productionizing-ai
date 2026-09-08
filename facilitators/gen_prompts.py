"""Generate the frozen question corpus.

Duplicates are DELIBERATE: at the morning rush many people ask the same thing
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

# Small hot pool -- the questions everybody asks at the morning rush.
BASE = [
    "What is in a caramel macchiato?",
    "How many pumps of syrup are in a grande?",
    "How many shots are in a grande latte?",
    "Is the pink drink dairy free?",
    "How much caffeine is in a grande cold brew?",
]

# Same meaning, different words: exact cache MISSES, semantic cache HITS.
NEAR = [
    "How do you make a caramel macchiato?",
    "How much syrup goes in a grande?",
    "How many espresso shots does a grande latte take?",
    "Can I get the pink drink without dairy?",
]

# The long tail: asked once, never again.
TAIL = [
    "What is a flat white built with?", "How long is cold brew steeped for?",
    "Which sauces contain dairy?",
    "What is the difference between a latte and a cappuccino?",
    "How many pumps of mocha sauce go in a venti iced?",
    "What is a caffe misto?",
    "What is in a java chip frappuccino?", "Is the matcha latte sweetened?",
    "How big is a venti iced?", "What is a ristretto?",
    "How hot is milk steamed by default?",
    "What goes in a vanilla sweet cream cold brew?",
    "Can I get a mocha without dairy?",
    "What is the difference between blonde and signature espresso?",
    "Why does a frappuccino need base?",
    "What is the difference between iced coffee and cold brew?",
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
