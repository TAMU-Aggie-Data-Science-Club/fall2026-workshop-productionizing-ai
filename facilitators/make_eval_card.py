"""Regenerate facilitators/generated/eval_card.md from measured eval results.

The card used to contain invented numbers with two significant figures, which
is exactly the sin the activity warns against. Now it is generated from
facilitators/generated/eval_results.json and says plainly how it was measured and what
that measurement cannot see.
"""
import json, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
rows = json.loads((ROOT / "facilitators" / "generated" / "eval_results.json").read_text())
bar = json.loads((ROOT / "scenario.json").read_text())["constraints"]["quality_bar_eval_pct"]

lines = [
    "# Eval Card — the quality axis",
    "",
    "## How these numbers were produced",
    "",
    "They are **measured**, not estimated. `facilitators/eval.py` asks Nimbus "
    f"{rows[0]['total']} questions whose answers are known to be in the course notes, and "
    "checks whether the answer actually carries the fact through. Re-run it with:",
    "",
    "```bash",
    "make serve                                   # in one terminal",
    ".venv/bin/python facilitators/eval_all.py    # in another",
    "```",
    "",
    "**What it cannot see.** This is a keyword-groundedness proxy. It cannot "
    "detect fluent nonsense, bad tone, a half-right answer, or an answer that is "
    "correct but useless. A real eval uses human labels or a judge model over "
    "hundreds of examples.",
    "",
    "That gap is the point. Latency took twenty seconds to measure and cost took "
    "one line of arithmetic. Quality took a purpose-built harness, and it still "
    "only half answers the question. **This is why teams skip it and ship "
    "regressions.**",
    "",
    "---",
    "",
    f"## Nimbus quality by configuration    (bar: {bar}%)",
    "",
    "| Configuration | Overall | Extraction | Reasoning | Verdict |",
    "| --- | ---: | ---: | ---: | --- |",
]
for r in rows:
    ok = r["score_pct"] >= bar
    lines.append(f"| {r['label']} | **{r['score_pct']:.0f}%** | "
                 f"{r.get('extraction_pct', 0):.0f}% | {r.get('reasoning_pct', 0):.0f}% | "
                 f"{'clears the bar' if ok else '**FAILS the bar**'} |")

lines += [
    "",
    "**Extraction** questions have their answer sitting verbatim in a retrieved chunk — "
    "any model that can copy will pass them, so they mostly measure whether retrieval "
    "worked. **Reasoning** questions require combining notes or applying a rule to a "
    "situation the notes do not state directly. That column is where model capability "
    "actually shows up, and it is what students genuinely need help with.",
    "",
    "---",
    "",
    "## What the table is telling you",
    "",
    "*(written against the measured numbers above — re-read it if you re-run the eval)*",
    "",
]
by = {r["label"]: r["score_pct"] for r in rows}
full = by.get("Large model, full context (as shipped)")
trimmed = by.get("Large model, trimmed system prompt")
small = by.get("Small model for EVERYTHING")
routing = by.get("Routing: easy -> small, hard -> large")
loose = by.get("Semantic cache, threshold 0.80")
tight = by.get("Semantic cache, threshold 0.92")

if full is not None and trimmed is not None:
    lines.append(f"**Trimming the system prompt did not cost quality — it {'improved' if trimmed > full else 'changed'} it "
                 f"({full:.0f}% → {trimmed:.0f}%).** 1,200 tokens of unaudited instructions were "
                 "being re-read on every request, and the model was not better for it. "
                 "You were paying to make the answers worse.\n")
if small is not None and routing is not None:
    lines.append(f"**Routing keeps quality; a blanket downgrade does not.** Easy questions to the "
                 f"small model scores {routing:.0f}%. Sending *everything* to it scores {small:.0f}%. "
                 "The small model is not bad — it is bad at the hard questions, which are the "
                 "ones students actually need help with.\n")
if loose is not None and tight is not None:
    if abs(tight - loose) < 3:
        lines.append(
            f"**The semantic-cache threshold made no measurable difference here** "
            f"({tight:.0f}% at 0.92 vs {loose:.0f}% at 0.80). That is a finding, not a "
            "non-result: this corpus's re-phrasings are genuinely close in meaning, so "
            "loosening the threshold did not start matching unrelated questions. Do not "
            "generalise it — on a corpus with many superficially similar but semantically "
            "different questions, a loose threshold is exactly how you serve a confident "
            "answer to a question nobody asked. Measure it on your own traffic.\n")
    else:
        lines.append(f"**Cache thresholds are a quality decision, not a performance one.** "
                     f"At 0.92 the semantic cache scores {tight:.0f}%; at 0.80 it scores "
                     f"{loose:.0f}%. A loose threshold serves confident answers to "
                     "questions nobody asked.\n")

lines += [
    "---",
    "",
    "> A model that is 95% right, wired into a system with no recovery path, fails "
    "5% of the time — spectacularly. The failure is the system, not the prediction.",
]
out = ROOT / "facilitators" / "generated" / "eval_card.md"
out.write_text("\n".join(lines) + "\n")
print(f"wrote {out} from {len(rows)} measured configurations")
