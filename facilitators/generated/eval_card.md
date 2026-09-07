# Eval Card — the quality axis

## How these numbers were produced

They are **measured**, not estimated. `facilitators/eval.py` asks Nimbus 36 questions whose answers are known to be in the course notes, and checks whether the answer actually carries the fact through. Re-run it with:

```bash
make serve                                   # in one terminal
.venv/bin/python facilitators/eval_all.py    # in another
```

**What it cannot see.** This is a keyword-groundedness proxy. It cannot detect fluent nonsense, bad tone, a half-right answer, or an answer that is correct but useless. A real eval uses human labels or a judge model over hundreds of examples.

That gap is the point. Latency took twenty seconds to measure and cost took one line of arithmetic. Quality took a purpose-built harness, and it still only half answers the question. **This is why teams skip it and ship regressions.**

---

## Nimbus quality by configuration    (bar: 80%)

| Configuration | Overall | Extraction | Reasoning | Verdict |
| --- | ---: | ---: | ---: | --- |
| Large model, full context (as shipped) | **94%** | 92% | 100% | clears the bar |
| Large model, trimmed system prompt | **97%** | 100% | 92% | clears the bar |
| Large model, reduced context (K=2) | **92%** | 92% | 92% | clears the bar |
| Large model, shorter answers (24 tokens) | **92%** | 92% | 92% | clears the bar |
| Routing: easy -> small, hard -> large | **92%** | 88% | 100% | clears the bar |
| Small model for EVERYTHING | **78%** | 83% | 67% | **FAILS the bar** |
| Semantic cache, threshold 0.92 | **94%** | 92% | 100% | clears the bar |
| Semantic cache, threshold 0.80 | **94%** | 92% | 100% | clears the bar |
| Everything on (rungs 2-4) | **92%** | 92% | 92% | clears the bar |

**Extraction** questions have their answer sitting verbatim in a retrieved chunk — any model that can copy will pass them, so they mostly measure whether retrieval worked. **Reasoning** questions require combining notes or applying a rule to a situation the notes do not state directly. That column is where model capability actually shows up, and it is what students genuinely need help with.

---

## What the table is telling you

*(written against the measured numbers above — re-read it if you re-run the eval)*

**Trimming the system prompt did not cost quality — it improved it (94% → 97%).** 1,200 tokens of unaudited instructions were being re-read on every request, and the model was not better for it. You were paying to make the answers worse.

**Routing keeps quality; a blanket downgrade does not.** Easy questions to the small model scores 92%. Sending *everything* to it scores 78%. The small model is not bad — it is bad at the hard questions, which are the ones students actually need help with.

**The semantic-cache threshold made no measurable difference here** (94% at 0.92 vs 94% at 0.80). That is a finding, not a non-result: this corpus's re-phrasings are genuinely close in meaning, so loosening the threshold did not start matching unrelated questions. Do not generalise it — on a corpus with many superficially similar but semantically different questions, a loose threshold is exactly how you serve a confident answer to a question nobody asked. Measure it on your own traffic.

---

> A model that is 95% right, wired into a system with no recovery path, fails 5% of the time — spectacularly. The failure is the system, not the prediction.
