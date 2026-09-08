"""Measure answer groundedness, so the eval card is data rather than invention.

This is a KEYWORD-GROUNDEDNESS PROXY, not a real quality eval: for each question
we know which fact the recipe notes contain, and we check whether the answer
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
# actually shows up -- and they are the questions customers genuinely need
# answered. A model that aces extraction and fails reasoning is exactly the failure
# mode that a naive eval misses.

# (question, any-of these terms means the answer carried the fact through)
CASES = [
    ("What is in a caramel macchiato?",               ["vanilla", "caramel", "upside down", "poured through"]),
    ("How many pumps of syrup are in a grande?",      ["4", "four"]),
    ("How many shots are in a grande latte?",         ["2", "two"]),
    ("How much caffeine is in a grande cold brew?",   ["205"]),
    ("How long is cold brew steeped for?",            ["20"]),
    ("How many ounces is a venti iced?",              ["24"]),
    ("What kind of shots go in a flat white?",        ["ristretto"]),
    ("How many pumps of sauce go in a venti iced?",   ["5", "five"]),
    ("What is a caffe misto?",                        ["brewed", "steamed milk", "no espresso"]),
    ("Which milk alternatives do you have?",          ["oatmilk", "soymilk", "almondmilk", "coconutmilk"]),
    ("What is in a pink drink?",                      ["coconutmilk", "strawberry"]),
    ("Is the matcha latte sweetened?",                ["pre-sweetened", "sweetened", "sugar"]),
    ("What is in a vanilla sweet cream cold brew?",   ["vanilla", "sweet cream"]),
    ("How hot is milk steamed by default?",           ["71"]),
    ("What temperature is an extra hot drink?",       ["82"]),
    ("What is in a hot chocolate?",                   ["mocha", "vanilla", "whipped cream"]),
    ("How much caffeine is in one shot of espresso?", ["75"]),
    ("What is in a java chip frappuccino?",           ["mocha", "chip", "whipped cream"]),
    ("How many scoops of matcha go in a grande?",     ["3", "three"]),
    ("What is nitro cold brew?",                      ["nitrogen", "tap", "without ice", "no ice"]),
    ("How many pumps of chai go in a venti iced?",    ["6", "six"]),
    ("What is an espresso con panna?",                ["whipped cream", "shot"]),
    ("How much caffeine is in a grande brewed coffee?", ["310"]),
    ("How many ounces is a short?",                   ["8"]),
]

CASES_HARD = [
    ("I am dairy free. Can I have a mocha?",
     ["cannot", "can not", "contains dairy", "mocha sauce", "not"]),
    ("I want an iced drink that is already dairy free as it is written. What should I order?",
     ["pink drink", "brown sugar", "oatmilk", "coconutmilk"]),
    ("A grande latte takes 4 pumps of vanilla. How many pumps of mocha sauce does a grande mocha take?",
     ["3", "three", "one fewer", "one less"]),
    ("I ordered a venti iced latte. How many shots is that?",
     ["3", "three"]),
    ("Can I get a cappuccino with less foam?",
     ["cannot", "no", "latte", "not"]),
    ("Can I have a decaf cold brew?",
     ["never", "no", "cannot", "overnight", "single batch"]),
    ("I want the most caffeine on the menu. What should I order?",
     ["brewed coffee", "310"]),
    ("I avoid dairy. Is a dairy free chai latte possible?",
     ["yes", "concentrate", "no dairy", "alternative milk", "oatmilk"]),
    ("Why can I not have my caramel macchiato stirred?",
     ["layer", "different drink", "vanilla latte", "not stirred", "upside down"]),
    ("I have a severe nut allergy. Can you promise me a safe almondmilk latte?",
     ["cannot", "shared", "barista", "rinsed", "not promise"]),
    ("Can I get a refresher with no caffeine at all?",
     ["green coffee", "no", "cannot", "caffeinated", "not"]),
    ("My child wants a warm drink with no coffee in it. What do you suggest, and how hot is it?",
     ["steamed milk", "54"]),
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
