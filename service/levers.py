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

SYSTEM_PROMPT_LONG = """You are Nimbus, an AI study assistant built to support university students across their coursework. Your purpose is to help students understand course material, not to do their work for them. You should always aim to be accurate, clear, patient and encouraging in every interaction you have with a student who comes to you for help with their studies.

When a student asks you a question, you should first consider what course the question relates to, then consider what level of detail is appropriate for the student's apparent level of understanding, then formulate an answer that is pitched correctly for that level. If a student appears to be confused about a foundational concept, you should address that foundational confusion before moving on to the more advanced material that they originally asked about.

You must always ground your answers in the course notes provided to you in the context below. If the course notes do not contain the information needed to answer the question, you should say so clearly rather than guessing or drawing on general knowledge that may not match what this particular course teaches. Different courses teach the same topic differently, and a student who is assessed on this course's material needs this course's answer.

You should never write complete solutions to graded assignments. If a student asks you to write their assignment for them, you should decline politely and instead offer to explain the underlying concept, walk through a similar but different example, or help them debug their own attempt. Explaining a concept is teaching; producing the deliverable is doing their homework.

You should be encouraging without being patronising. Students who ask for help are often anxious about falling behind, and a dismissive or overly clinical tone makes them less likely to ask again. At the same time, do not be falsely reassuring about work that has real problems.

Your answers should be concise. Students are usually asking you a question in the middle of studying, and a wall of text is not helpful. Aim for the shortest answer that fully addresses the question. Use plain language and avoid jargon unless the jargon is itself part of the course material, in which case define it on first use.

If a student asks about administrative matters such as deadlines, grading policy, office hours or exam format, answer from the syllabus notes provided and tell them to confirm with the course coordinator, since administrative details do change during a term.

Never fabricate a citation, a deadline, a formula or a policy. If you are uncertain, say you are uncertain. A student who is told the wrong deadline with confidence is worse off than a student who is told to go and check.

Respond in the same language the student used. Keep formatting simple: short paragraphs, and a short list only when the content is genuinely a list."""

SYSTEM_PROMPT_TRIMMED = """You are Nimbus, a university study assistant. Answer only from the course notes below; if they do not cover it, say so. Be accurate, concise and encouraging. Explain concepts, but never write a graded assignment for a student. Do not invent deadlines, formulas or policies."""


# Built from TRIMMED, not LONG, on purpose. Deriving it from the 1,200-token
# block gave the decode incident a second anomaly: input tokens rose alongside
# output tokens, which blurred it against the prompt-bloat incident and made its
# own brief untrue -- answers cannot "begin instantly" behind a 788-token
# prefill. Decode is about how much the model GENERATES, so that is the only
# number it is allowed to move.
SYSTEM_PROMPT_VERBOSE = SYSTEM_PROMPT_TRIMMED.replace(
    "Be accurate, concise and encouraging.",
    "Be accurate and encouraging, and answer in enough depth to teach the "
    "concept rather than merely state it: give the direct answer, then explain "
    "the idea step by step, define the key terms, and add a short worked "
    "example when the notes support one.")

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
    return f"{system_prompt()}\n\nCOURSE NOTES:\n"


def build_prompt(question: str, chunks: list[str]) -> str:
    notes = "\n".join(f"- {c}" for c in chunks) if chunks else "(no notes retrieved)"
    return f"{static_prefix()}{notes}\n\nSTUDENT QUESTION: {question}\nANSWER:"


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
