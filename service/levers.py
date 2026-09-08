"""Every scaling lever, one small independent piece each.

They are kept independent on purpose: that is what lets a team change ONE thing,
re-measure, and attribute the difference to that thing. A tangle of interacting
options would make the ladder unclimbable.
"""
import hashlib

import numpy as np

import config
from embed import embed_one

# ── System prompts ────────────────────────────────────────────────────────
# The LONG one is what Nimbus shipped with: written by three different people
# over six months, never audited, re-read by the model on every single request.
# The TRIMMED one says the same thing.
# The VERBOSE one keeps the grounding and safety rules but asks for a fuller
# teaching response. It exists for the decode incident, where output work is
# intentionally the bottleneck.

SYSTEM_PROMPT_LONG = """You are Nimbus, the recipe assistant for a coffee bar. Your purpose is to tell a barista or a customer exactly how a drink is built — the shots, the syrups, the milk and the order they go into the cup — accurately and quickly, for someone who is standing at the bar with a queue behind them.

When somebody asks you about a drink, you should first work out whether they are asking for a full recipe, for one component such as the number of pumps, or for a rule that applies across the menu, then find the relevant entry in the recipe notes provided below, and answer with the specific detail they asked for rather than a general description of the drink. Somebody asking how many pumps go in a Grande wants the number first and the explanation second.

You must always ground your answers in the recipe notes provided to you in the context below. If the recipe notes do not contain what is needed to answer, say so clearly and say what you do cover, rather than guessing or drawing on general knowledge about coffee that may not match how this bar builds its drinks. Recipes, pump counts and sizes differ between cafes, and somebody making a drink on this bar needs this bar's build.

Allergen and dietary questions deserve particular care. State exactly what the notes say about an ingredient, including any shared equipment warning, and never reason your way to a conclusion the notes do not support. If somebody describes an allergy and the notes do not settle the question, tell them to ask the barista rather than offering a best guess. An incorrect allergen answer is the one mistake here that can actually hurt somebody.

Never invent a pump count, a shot count, an ingredient or a drink that is not in the notes. If you are uncertain, say you are uncertain. Somebody who is confidently told the wrong build makes the drink wrong and does not find out until it is handed over.

Size is the thing people get wrong most often, so treat it as part of every recipe answer rather than as an afterthought. Pump counts, shot counts and scoop counts all change with the cup, and the iced sizes do not match the hot ones, so an answer that gives a number without saying which size it belongs to is not a useful answer. If somebody asks for a build without naming a size, give the Grande and say that is what you have given them.

Some drinks are defined by a ratio or a construction rather than by their ingredients alone, and those cannot be modified into something else while keeping the name. Where the notes say a drink is built in a particular order, or with a particular kind of shot, or with a fixed proportion of foam, pass that on as part of the recipe and say plainly what happens if it is changed, because somebody who alters it is no longer making the drink they asked for."""

SYSTEM_PROMPT_TRIMMED = """You are Nimbus, the recipe assistant for a coffee bar. Answer only from the recipe notes below; if they do not cover it, say so. Be accurate, brief and friendly. For allergen questions state exactly what the notes say and never guess. Do not invent pump counts, shot counts or ingredients."""


# Built from TRIMMED, not LONG, on purpose. Deriving it from the 1,200-token
# block gave the decode incident a second anomaly: input tokens rose alongside
# output tokens, which blurred it against the prompt-bloat incident and made its
# own brief untrue -- answers cannot "begin instantly" behind a 788-token
# prefill. Decode is about how much the model GENERATES, so that is the only
# number it is allowed to move.
SYSTEM_PROMPT_VERBOSE = SYSTEM_PROMPT_TRIMMED.replace(
    "Be accurate, brief and friendly.",
    "Be accurate and friendly, and answer in enough depth to be genuinely "
    "useful rather than merely correct: give the direct answer, then explain "
    "what goes into the drink, note anything that restricts it such as a size "
    "or a fixed ratio, and suggest one alternative when the notes support one.")

def system_prompt() -> str:
    if config.SYSTEM_PROMPT == "VERBOSE":
        return SYSTEM_PROMPT_VERBOSE
    return SYSTEM_PROMPT_LONG if config.SYSTEM_PROMPT == "LONG" else SYSTEM_PROMPT_TRIMMED


def static_prefix() -> str:
    """The part of every prompt that never changes -- the prefix cache's target.

    Prompt order is a design decision, not an accident: static block first,
    varying content last. A prefix cache only helps up to the first byte that
    differs, so moving anything dynamic earlier would destroy the hit rate.
    """
    return f"{system_prompt()}\n\nMENU NOTES:\n"


def build_prompt(question: str, chunks: list[str]) -> str:
    notes = "\n".join(f"- {c}" for c in chunks) if chunks else "(no notes retrieved)"
    return f"{static_prefix()}{notes}\n\nCUSTOMER QUESTION: {question}\nANSWER:"


# ── Exact-match RESPONSE cache ────────────────────────────────────────────
_exact: dict[str, str] = {}


def exact_get(prompt: str) -> str | None:
    if not config.RESPONSE_CACHE:
        return None
    return _exact.get(hashlib.sha256(prompt.encode()).hexdigest())


def exact_put(prompt: str, answer: str) -> None:
    if config.RESPONSE_CACHE:
        _exact[hashlib.sha256(prompt.encode()).hexdigest()] = answer


# ── Semantic cache ────────────────────────────────────────────────────────
# Catches questions that MEAN the same thing but are not spelled the same way.
# Reuses the embedding model retrieval already loaded, so the marginal cost is
# one vector comparison.
_sem_vectors: list[np.ndarray] = []
_sem_answers: list[str] = []


def question_vector(question: str) -> np.ndarray | None:
    """Embed the question once per request.

    The lookup and the later store both need this vector. Computing it twice
    charged the semantic cache for work it never actually had to do, which made
    the lever look more expensive than it is.
    """
    return embed_one(question) if config.SEMANTIC_CACHE else None


def semantic_get(question: str, vec=None) -> str | None:
    if not config.SEMANTIC_CACHE or not _sem_vectors:
        return None
    if vec is None:
        vec = embed_one(question)
    scores = np.vstack(_sem_vectors) @ vec
    best = int(np.argmax(scores))
    if scores[best] >= config.SEMANTIC_CACHE_THRESHOLD:
        return _sem_answers[best]
    return None


def semantic_put(question: str, answer: str, vec=None) -> None:
    if not config.SEMANTIC_CACHE:
        return
    _sem_vectors.append(vec if vec is not None else embed_one(question))
    _sem_answers.append(answer)


# ── Routing ───────────────────────────────────────────────────────────────
EASY_STARTERS = ("what is", "what are", "define", "when is", "when are",
                 "where is", "where are", "who is", "how many", "list the")


def pick_tier(question: str) -> str:
    """A heuristic, not a trained classifier.

    The lesson is that routing is a lever. A trained router would teach the same
    lesson while costing a training step, an artifact and a new failure mode.
    """
    if config.MODEL_TIER == "small":
        return "small"          # the trap: everything to the cheap model
    if not config.ROUTE_EASY:
        return "large"
    q = question.strip().lower()
    if len(q.split()) <= 12 and q.startswith(EASY_STARTERS):
        return "small"
    return "large"


def reset_caches() -> None:
    """Drop every cached answer. Called on /reload so each lever change is
    measured from cold, not against answers built under the previous config."""
    _exact.clear()
    _sem_vectors.clear()
    _sem_answers.clear()


def cache_stats() -> dict:
    return {"exact_entries": len(_exact), "semantic_entries": len(_sem_answers)}
