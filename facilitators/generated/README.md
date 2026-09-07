# Generated from measurement — do not hand-edit

Every file in this directory is written by a script that measured something.
Editing one by hand produces a card that states a number nobody measured, which
is worse than having no card: the facilitator reads it out with confidence.

| Artifact | Written by | Reads |
|---|---|---|
| `signatures.json` | `facilitators/calibrate_incidents.py` | a live server per incident |
| `incident_panels/` | `facilitators/calibrate_incidents.py` | the same run |
| `incident_payloads/` | `facilitators/calibrate_incidents.py` | the same run |
| `eval_results.json` | `facilitators/eval_all.py` | a live server, one config at a time |
| `eval_card.md` | `facilitators/make_eval_card.py` | `eval_results.json` |

Regenerate, in this order:

```bash
python facilitators/calibrate_incidents.py     # -> signatures.json, panels, payloads
.venv/bin/python facilitators/eval_all.py      # -> eval_results.json
.venv/bin/python facilitators/make_eval_card.py
```

Two things make a regeneration wrong rather than merely stale:

- **Run nothing else while calibrating.** Measurements taken alongside other
  work came out about 1.7x inflated and produced a wrong answer key.
- **`calibrate_incidents.py` and `eval_all.py` patch `service/config.py` and
  restore it in a `finally`.** A killed run leaves it patched, and the next
  "baseline" silently measures caching already switched on.

Anything here is only as current as the backend and workload it was measured
against. After changing the corpus, the system prompt, retrieval settings or the
model tiers, these files are historical until they are regenerated.
