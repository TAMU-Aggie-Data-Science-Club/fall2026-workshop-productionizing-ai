"""Measure answer groundedness, so the eval card is data rather than invention.

This is a KEYWORD-GROUNDEDNESS PROXY, not a real quality eval: for each question
we know which fact the menu notes contain, and we check whether the answer
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
    ("What is in a flat white?",                     ["ristretto", "160", "8 oz"]),
    ("How much does a latte cost?",                  ["4.50", "5.00"]),
    ("What time do you close on Sunday?",            ["16:00", "16.00", "4 pm", "4pm"]),
    ("Does oat milk cost extra?",                    ["free", "no extra", "substitut"]),
    ("How much caffeine is in a cold brew?",         ["200"]),
    ("Which milk alternatives do you have?",         ["oat", "almond", "soy"]),
    ("Is the fruit cup vegan?",                      ["vegan", "gluten free"]),
    ("What allergens are in an almond croissant?",   ["wheat", "dairy", "egg", "almond"]),
    ("How does the loyalty card work?",              ["tenth", "free"]),
    ("Do you take cash?",                            ["card", "dining dollars", "2024", "stopped", "no longer"]),
    ("What is a cortado?",                           ["60", "4 oz", "equal part"]),
    ("How long is cold brew steeped for?",           ["18"]),
    ("What is the student discount?",                ["ten percent", "10 percent", "10%", "student id"]),
    ("Where is the cafe?",                           ["evans", "library", "annexe", "quad"]),
    ("What is the soup on Monday?",                  ["tomato", "basil", "vegan"]),
    ("How much is a bagel with cream cheese?",       ["4.00"]),
    ("What time does the grill switch off?",         ["15:00", "15.00", "3 pm", "3pm"]),
    ("How many seats are there?",                    ["forty", "40"]),
    ("What is in a mocha?",                          ["chocolate sauce", "espresso", "dairy"]),
    ("How long do you keep lost property?",          ["seven day", "7 day"]),
    ("Is there decaf drip coffee?",                  ["18:00", "18.00", "6 pm", "after"]),
    ("What are the seasonal drinks right now?",      ["maple", "apple"]),
    ("How much notice do you need for catering?",    ["two working day", "2 working day", "twelve", "12"]),
    ("How much is an extra espresso shot?",          ["1.00", "65"]),
]

CASES_HARD = [
    ("I am dairy free. Can I have a mocha?",
     ["cannot", "can not", "chocolate sauce", "contains dairy", "not"]),
    ("I want the most caffeine for the least money. What should I order?",
     ["drip"]),
    ("I have coeliac disease. What is actually safe for me here?",
     ["flourless", "fruit cup"]),
    ("I am vegan. Can I eat the banana bread?",
     ["egg", "not vegan", "cannot", "no"]),
    ("I have a severe nut allergy. Can you promise me a safe latte?",
     ["cannot guarantee", "shared", "barista", "dedicated"]),
    ("It is 16:00 and I would like a toasted bagel. Is that possible?",
     ["15:00", "15.00", "grill", "off", "cannot", "no"]),
    ("Can I get a 16 oz cappuccino?",
     ["12", "only", "cannot", "fixed", "ratio"]),
    ("I avoid dairy. Is a dairy free chai latte possible?",
     ["yes", "concentrate", "no dairy", "alternative milk", "oat"]),
    ("It is Sunday at 15:50. Can I still order a coffee?",
     ["15:45", "fifteen minutes", "last order", "no", "closed"]),
    ("I want less caffeine than a double espresso but not none. What do you suggest?",
     ["matcha", "70"]),
    ("Two of us want to study quietly for three hours during finals. Is that fine?",
     ["two hour", "2 hour", "quiet", "bar", "limit"]),
    ("Can I use my student discount on the half price evening pastries?",
     ["not stack", "does not stack", "cannot", "no"]),
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
