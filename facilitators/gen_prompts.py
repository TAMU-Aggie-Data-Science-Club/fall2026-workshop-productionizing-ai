"""Generate the frozen question corpus.

Duplicates are DELIBERATE: at the morning rush many customers ask the same thing
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
    "What is in a flat white?",
    "Does the oat milk cost extra?",
    "What time do you close today?",
    "Is the banana bread vegan?",
    "How much caffeine is in a cold brew?",
]

# Same meaning, different words: exact cache MISSES, semantic cache HITS.
NEAR = [
    "What goes into a flat white?",
    "Do you charge more for oat milk?",
    "When do you shut this evening?",
    "Can I eat the banana bread if I am vegan?",
]

# The long tail: asked once, never again.
TAIL = [
    "What is a cortado?", "Do you have decaf cold brew?",
    "Which pastries contain nuts?",
    "What is the difference between a latte and a cappuccino?",
    "How does the loyalty card work?",
    "Can I pay with dining dollars?",
    "What is the soup today?", "Is the fruit cup gluten free?",
    "Do you take cash?", "What size is a flat white?",
    "How long does food take at peak?",
    "Where do I pick up a mobile order?",
    "Can I get a mocha without dairy?",
    "What is on the autumn seasonal menu?",
    "Do you give a discount for bringing my own cup?",
    "What happens to unsold pastries at the end of the day?",
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
