"""Measure answer groundedness, so the eval card is data rather than invention.

This is a KEYWORD-GROUNDEDNESS PROXY, not a real quality eval: for each question
we know which fact the course notes contain, and we check whether the answer
actually contains it. It cannot detect fluent nonsense, tone, or partial
correctness, and a real eval would use human labels or a judge model.

It is deliberately shipped anyway, because a crude measured number beats a
confident invented one -- and the gap between this and a real eval is exactly
the point the activity makes about quality being the expensive axis.

Usage:  .venv/bin/python facilitators/eval.py            # current server config
"""
import argparse, json, os, pathlib, sys, urllib.request

# Two tiers, because they measure different things.
#
# EXTRACTION: the answer sits verbatim in a retrieved chunk. Any model that can
# copy will pass these, so they mostly measure whether RETRIEVAL worked.
#
# REASONING: the answer requires combining notes, or applying a rule to a
# situation the notes do not state directly. These are where model capability
# actually shows up -- and they are the questions students genuinely need help
# with. A model that aces extraction and fails reasoning is exactly the failure
# mode that a naive eval misses.

# (question, any-of these terms means the answer carried the fact through)
CASES = [
    ("What does the learning rate do?",              ["step size", "diverge", "too large"]),
    ("What is overfitting?",                         ["generalis", "generaliz", "training data", "noise"]),
    ("What is the difference between a list and a tuple?", ["mutable", "immutable"]),
    ("When are office hours?",                       ["tuesday", "thursday", "14:00", "10:00"]),
    ("What is Big-O notation?",                      ["growth", "input size", "constant"]),
    ("What is cross-validation?",                    ["fold", "split", "validat"]),
    ("What is a p-value?",                           ["null", "probability", "extreme"]),
    ("What is the difference between the mean and the median?", ["middle", "outlier", "average"]),
    ("What sorting algorithm does Python use?",      ["timsort"]),
    ("How does binary search work?",                 ["sorted", "half", "log"]),
    ("What is the difference between precision and recall?", ["predicted positive", "actual positive", "positives"]),
    ("What is L1 regularisation?",                   ["zero", "feature selection"]),
    ("What is the grading breakdown for this course?", ["40", "30", "20"]),
    ("What happens if I submit an assignment late?", ["10 percent", "10%", "three days", "per day"]),
    ("How long is the midterm?",                     ["90", "minute"]),
    ("What is gradient descent?",                    ["loss", "iterat", "direction", "parameters"]),
    ("Define variance.",                             ["squared", "deviation", "mean"]),
    ("What is a confusion matrix?",                  ["true positive", "false positive", "counts"]),
    ("What is feature scaling and when do I need it?", ["standardis", "standardiz", "unit variance", "range"]),
    ("What is the bias-variance tradeoff?",          ["bias", "variance", "complex"]),
    ("What does the 'finally' block do in Python?",  ["always", "cleanup", "clos"]),
    ("Define recursion.",                            ["itself", "base case"]),
    ("What is a confidence interval?",               ["95", "range", "parameter", "contain"]),
    ("What is the difference between a stack and a queue?", ["last-in", "first-in", "lifo", "fifo", "first out"]),
]

CASES_HARD = [
    ("My model gets 99% accuracy on training data but 70% on test data. What is happening?",
     ["overfit", "memoris", "memoriz", "generalis", "generaliz"]),
    ("My dataset is 99% one class. Why is accuracy a bad metric here, and what should I use?",
     ["imbalanc", "precision", "recall", "f1", "misleading"]),
    ("My gradient descent loss keeps oscillating and getting bigger. What is the most likely cause?",
     ["learning rate", "too large", "diverg", "step"]),
    ("Why can a tuple be a dictionary key when a list cannot?",
     ["immutable", "hashable", "mutable"]),
    ("I standardised my features before training a decision tree and nothing changed. Why?",
     ["tree", "do not need", "don't need", "not need", "scal"]),
    ("Should I use binary search on an unsorted list?",
     ["no", "sorted", "must be sorted", "linear"]),
    ("I only have a small dataset and want to compare two models fairly. What procedure should I use?",
     ["cross-validation", "cross validation", "k-fold", "fold"]),
    ("Which is more affected by a single extreme outlier, the mean or the median?",
     ["mean"]),
    ("I have a heavy workload in my other courses. Can I get a deadline extension?",
     ["no", "not grounds", "illness", "emergency", "documented"]),
    ("My recursive function crashes with RecursionError on large inputs. What would you change?",
     ["base case", "iterativ", "stack", "loop", "depth"]),
    ("I want to reduce my feature count automatically. Which regularisation should I pick?",
     ["l1", "zero", "feature selection"]),
    ("Can I paste code from an AI assistant straight into my submission?",
     ["declar", "explain", "no", "must be able"]),
]


def ask(url: str, question: str) -> str:
    req = urllib.request.Request(
        f"{url}/ask", method="POST",
        data=json.dumps({"question": question}).encode(),
        headers={"Content-Type": "application/json"})
    parts = []
    complete = False
    stats = None
    error = False
    with urllib.request.urlopen(req, timeout=300) as r:
        for raw in r:
            line = raw.decode().strip()
            if line == "data: [DONE]":
                complete = True
                break
            if line.startswith("data: "):
                ev = json.loads(line[6:])
                if "delta" in ev:
                    parts.append(ev["delta"])
                elif "stats" in ev:
                    stats = ev["stats"]
                elif "error" in ev:
                    error = True
    return "".join(parts) if complete and stats and not error else ""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=os.environ.get("NIMBUS_URL", "http://127.0.0.1:8000"))
    ap.add_argument("--admin-token", default=os.environ.get("NIMBUS_ADMIN_TOKEN", ""),
                    help="token for protected /metrics; never sent to /ask")
    ap.add_argument("--label", default="")
    args = ap.parse_args()
    args.url = args.url.rstrip("/")

    metrics_request = urllib.request.Request(
        f"{args.url}/metrics",
        headers={"X-Nimbus-Admin-Token": args.admin_token} if args.admin_token else {})
    cfg = json.loads(urllib.request.urlopen(metrics_request, timeout=10)
                     .read().decode())["config"]

    def score_set(cases):
        hits, misses = 0, []
        for question, terms in cases:
            try:
                answer = ask(args.url, question).lower()
            except Exception:
                answer = ""
            if any(t.lower() in answer for t in terms):
                hits += 1
            else:
                misses.append(question)
        return hits, misses

    e_hits, e_miss = score_set(CASES)
    h_hits, h_miss = score_set(CASES_HARD)
    total = len(CASES) + len(CASES_HARD)
    overall = (e_hits + h_hits) / total * 100

    out = {"label": args.label,
           "score_pct": round(overall, 1),
           "extraction_pct": round(e_hits / len(CASES) * 100, 1),
           "reasoning_pct": round(h_hits / len(CASES_HARD) * 100, 1),
           "hits": e_hits + h_hits, "total": total,
           "config": cfg, "missed": e_miss + h_miss}
    print(json.dumps(out))
    print(f"\n{args.label or 'current config'}: overall {overall:.0f}%  "
          f"(extraction {out['extraction_pct']:.0f}%, "
          f"reasoning {out['reasoning_pct']:.0f}%)", file=sys.stderr)


if __name__ == "__main__":
    main()
