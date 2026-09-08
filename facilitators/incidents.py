"""The incident catalog. NOT FOR PARTICIPANTS.

service/incident.py holds the mechanism; this file holds the answers. The
split is the point: a participant with the whole repository checked out can read
the mechanism and learn that a retrieval delay is possible, but not that theirs
is one. Everything below reaches a running service as deploy-time environment
variables, so it is never present in the code they can see.

Two rules govern the set.

UNIQUE DISCRIMINATORS. Every incident owns at least one signal that no other
incident moves. If two incidents move the same signals by the same amounts the
diagnosis is a coin flip, and the room correctly concludes that diagnosis does
not work. `calibrate_incidents.py` checks this against measured data and fails
rather than shipping a collision.

QUEUE STARVATION MASKS EVERYTHING. The shipped default admits 2 requests while
the benchmark offers 8, so queue wait dominates the ledger no matter what else
is wrong. That IS the queue incident -- and it would flatten every other
signature into the same shape. So each non-queue incident raises MAX_CONCURRENT
to the benchmark's concurrency, which takes the queue out of the story and lets
the injected fault be the story.
"""

# Taking the queue out of the story: OFFER less traffic, do not admit more.
#
# Raising MAX_CONCURRENT to the benchmark's concurrency looks equivalent and is
# not. Admitting 8 concurrent generations on a box with 4 cores does not create
# capacity; it relocates the waiting from the queue into generation, so every
# non-queue incident measured 96% "generate" and the panel would have told
# participants the model was at fault in all of them. Offering traffic at the
# admission limit leaves the queue empty AND the cores uncontended, so the
# injected fault is the only thing left to find.
#
# Traffic shape is part of an incident's definition, not a global constant --
# different incidents are reported by different traffic in the real world too.
_CALM = {"requests": 16, "rate": 1.0, "concurrency": 2}
_SURGE = {"requests": 16, "rate": 4.0, "concurrency": 8}

# The reference measurement every "is this anomalous?" question is asked
# against. NOT the shipped default -- the shipped default already carries the
# 1,200-token system prompt, so measuring the prompt-bloat incident against it
# showed a 1.5x increase instead of the 6x a participant needs to see.
#
# Caches are OFF here deliberately. A cache hit performs no model call and
# reports zero tokens, so a cached reference run would deflate the very token
# baseline the prompt and decode incidents are compared against. This is a
# clean measuring stick, not a recommended configuration.
HEALTHY_ENV = {
    # Pinned, not inherited. Leaving admission to whatever the file or the
    # deployment happened to set makes "healthy" mean one thing on a laptop and
    # another on Cloud Run, and every comparison against it meaningless.
    "NIMBUS_MAX_CONCURRENT": "2",
    "NIMBUS_SYSTEM_PROMPT": "TRIMMED",
    "NIMBUS_RETRIEVE_K": "3",
    "NIMBUS_MAX_TOKENS": "32",
    "NIMBUS_MODEL_TIER": "large",
    "NIMBUS_RESPONSE_CACHE": "false",
    "NIMBUS_SEMANTIC_CACHE": "false",
    "NIMBUS_ROUTE_EASY": "false",
}
HEALTHY_TRAFFIC = _CALM

INCIDENTS = {

    "queue": {
        "public_title": "Everyone is waiting",
        "traffic": _SURGE,
        "expect": {"dominant": "queue"},
        "title": "Finals week",
        "public_symptom": "Every customer is waiting, and it is worse at busy times.",
        "user_impact": "Answers that used to arrive in seconds now take most of a minute.",
        # Nothing injected. The bottleneck is real: admission of ONE request
        # against an offered concurrency of 8. Stated explicitly rather than
        # inherited from config.py's file defaults, which a deployed service
        # does not have -- and so that the ONLY thing wrong here is the queue.
        #
        # Admission of 2 was measured at p95 1.57-1.92s against a healthy run of
        # 0.74-1.05s. The gap is real but narrow enough that ordinary provider
        # variance can close it, and a verdict that flips on Gemini having a
        # slow minute is not a verdict. At 1 the same incident measures
        # 3.19-3.62s: three times a healthy run, and no SLO that passes healthy
        # can miss it.
        "env": {**HEALTHY_ENV, "NIMBUS_MAX_CONCURRENT": "1"},
        "private_truth": "Admission control (2) is far below the arrival concurrency (8).",
        "discriminator": "app queue wait dominates while token counts sit at baseline",
        "tempting_wrong_fix": "Blame the model and downgrade the tier.",
        "correct_path": "Remove work from the queue (caching), then route, then capacity.",
        "backends": ("local", "ollama", "google"),
        "round": 1,
    },

    "retrieval": {
        "public_title": "Slow to start answering",
        "traffic": _CALM,
        "expect": {"dominant": "retrieve"},
        "title": "The new vector store",
        "public_symptom": "Slow to START answering. The answer itself reads fine.",
        "user_impact": "Students stare at a blank box, then get a good answer.",
        # Sized against the deployment it runs on, because "dominant" is a
        # RATIO and generation time is the denominator. Managed Gemini answers
        # in about 1.2s at p95, so a realistic p95 of 1.8s for a degraded vector
        # store makes retrieval ~60% of the budget. The local SmolLM tiers take
        # 4-7s, where the same 1.8s would be 4% and the panel would blame the
        # model -- the exact confusion this incident exists to break. For a
        # local run, override with retrieve:lognormal:2000:8000.
        "env": {**HEALTHY_ENV,
                "NIMBUS_INCIDENT_STAGE_DELAY": "retrieve:lognormal:400:1800"},
        "private_truth": ("Course notes moved to a hosted vector store with a "
                          "reranker. Correct, better, and p95 1.8s with a fat tail."),
        "discriminator": "retrieve is the dominant ledger row; generate is at baseline",
        "tempting_wrong_fix": ("Downgrade the model or cut MAX_TOKENS -- both are "
                               "falsifiable in one run, because neither touches "
                               "the stage that is actually slow."),
        "correct_path": ("The semantic cache is checked BEFORE retrieval, so a hit "
                         "skips the slow dependency entirely."),
        "backends": ("local", "ollama", "google"),
        "round": 2,
    },

    "prompt": {
        "public_title": "The bill tripled",
        "traffic": _CALM,
        "expect": {"signal": "tokens_in", "at_least_x": 3.0},
        "title": "Tuesday's pull request",
        "public_symptom": "The bill tripled. Latency is somewhat worse.",
        "user_impact": "Finance noticed before engineering did.",
        # Healthy is TRIMMED at K=3; the regression is both halves of the
        # "better grounding" change that shipped on Tuesday.
        "env": {**HEALTHY_ENV,
                "NIMBUS_RETRIEVE_K": "12",
                "NIMBUS_SYSTEM_PROMPT": "LONG"},
        "private_truth": "A 'better grounding' change took RETRIEVE_K from 4 to 12.",
        "discriminator": "input tokens far above baseline; output tokens unchanged",
        "tempting_wrong_fix": ("Add capacity. Latency improves slightly and the "
                               "monthly number gets worse, because the regression "
                               "is per-request and capacity multiplies it."),
        "correct_path": "Trim the prompt and the retrieved context; then check quality.",
        "backends": ("local", "ollama", "google"),
        "round": 2,
    },

    "decode": {
        "room_enabled": False,  # experimental until failure AND recovery are verified
        "public_title": "Answers crawl to the end",
        "traffic": _CALM,
        "expect": {"signal": "tokens_out", "at_least_x": 3.0},
        "title": "Helpfulness creep",
        "public_symptom": "Answers begin instantly, then crawl to the end.",
        "user_impact": "Students read the first line and wait for the rest.",
        # This is the incident where the model REALLY is the bottleneck. Without
        # it, "never blame the LLM" becomes the winning strategy -- the same
        # reflex the activity exists to break, pointed the other way.
        "env": {**HEALTHY_ENV,
                "NIMBUS_MAX_TOKENS": "256",
                "NIMBUS_SYSTEM_PROMPT": "VERBOSE",
                "NIMBUS_GEMINI_THINKING_BUDGET": "128",
                "NIMBUS_GOOGLE_MODEL_LARGE": "gemini-2.5-pro"},
        "private_truth": ("The output cap was raised 32 -> 256, then the large "
                          "tier was moved to Gemini 2.5 Pro with thinking enabled "
                          "and a verbose answer prompt."),
        "discriminator": "output tokens far above baseline, with generate dominant",
        "tempting_wrong_fix": ("Turn on every cache. The tail of the corpus is "
                               "mostly unique questions, so the hit rate barely "
                               "moves and neither does p95."),
        "correct_path": ("Cap the output, then route. This is where the cheap-model "
                         "shortcut is genuinely on the table -- and where the eval "
                         "card fires."),
        "backends": ("local", "ollama", "google"),
        "round": 2,
    },

    "upstream": {
        "room_enabled": False,  # experimental until failure AND recovery are verified
        "public_title": "Intermittent failures",
        "traffic": _CALM,
        "expect": {"signal": "retries", "at_least": 3},
        "title": "The provider is having a day",
        "public_symptom": "Mostly fine. Occasionally terrible. A few outright failures.",
        "user_impact": "One customer in six waits twice as long; one in two hundred gets nothing.",
        # 0.25, chosen by measuring the ACTUAL corpus rather than from the
        # binomial. The fault is seeded from the assembled prompt, so for a
        # fixed corpus and configuration the same requests fault every run --
        # the incident is reproducible, not a dice roll. Against the first 16
        # benchmark questions:
        #
        #     0.17, 0.20   1 request retried,  0 failed   -- barely a tell
        #     0.25+        5 requests retried, 1 failed   -- unmistakable
        #
        # At 0.17 a team saw "provider retries 1" and little else. At 0.25 the
        # run reports 15 ok / 1 failed alongside the retry count, which is what
        # a rate-limiting provider actually looks like from the inside.
        # RE-CHECK this against the corpus after any change to the questions,
        # the system prompt or RETRIEVE_K: they all change the prompt, and the
        # prompt is the seed.
        "env": {**HEALTHY_ENV,
                "NIMBUS_INCIDENT_PROVIDER_FAULT": "0.25:429"},
        "private_truth": ("The managed endpoint rate-limits ~1 call in 6. The "
                          "adapter already retries with backoff, silently."),
        # The retry counter is the tell that survives a 16-request run. The fat
        # tail is real -- about one request in six is retried, so p99 sits well
        # above p95 -- but at this sample size p99 IS the slowest request and
        # p95 the second slowest, so their ratio is one unlucky draw rather than
        # evidence. Run 50+ requests if you want the tail to carry weight.
        "discriminator": ("non-zero provider retries, with every stage normal on "
                          "the requests that succeeded"),
        "tempting_wrong_fix": ("Raise concurrency to push through the backlog, "
                               "which sends MORE concurrent calls at a "
                               "rate-limiting provider and is strictly worse."),
        "correct_path": "Shed early and honestly, bound the retry budget, fall back a tier.",
        # The fault is raised inside the HTTP adapters' real retry loops. The
        # in-process local backend has no retry loop and cannot produce this.
        "backends": ("ollama", "google"),
        "round": 2,
    },

    "staleness": {
        "room_enabled": False,  # experimental until failure AND recovery are verified
        "public_title": "Wrong answers, healthy dashboards",
        "traffic": _CALM,
        "expect": {"infra_passes": True},
        "title": "Green dashboards",
        "public_symptom": "Nobody has complained about speed. Tutors say the answers are wrong.",
        "user_impact": "Students are confidently told the wrong thing.",
        "env": {**HEALTHY_ENV,
                "NIMBUS_SEMANTIC_CACHE": "true",
                "NIMBUS_SEMANTIC_CACHE_THRESHOLD": "0.55"},
        "private_truth": "The similarity threshold was loosened 0.92 -> 0.55 to lift hit rate.",
        # Separates from `cheapmodel` on WHERE the quality fails: a stale cache
        # serves the wrong answer to any question, so extraction fails too. A
        # too-small model still copies facts correctly and only fails reasoning.
        "discriminator": ("every infrastructure signal PASSES; quality fails across "
                          "BOTH extraction and reasoning"),
        "tempting_wrong_fix": "Ship it. Nothing in the benchmark objects.",
        "correct_path": "Run the eval. Notice the hit rate was the only number that looked too good.",
        "backends": ("local", "ollama", "google"),
        "round": "reveal",
    },

    "cheapmodel": {
        "room_enabled": False,  # experimental until failure AND recovery are verified
        "public_title": "Answers got shallow",
        "traffic": _CALM,
        "expect": {"infra_passes": True},
        "title": "The cheap-model shortcut",
        "public_symptom": "Fast and cheap. Tutors say answers got shallow.",
        "user_impact": "Simple questions are fine. The ones customers actually need answered are not.",
        "env": {**HEALTHY_ENV, "NIMBUS_MODEL_TIER": "small"},
        "private_truth": "Every request goes to the small model.",
        "discriminator": ("quality fails on REASONING while extraction holds -- the "
                          "small model can still copy a fact out of a retrieved chunk"),
        "tempting_wrong_fix": "Ship it; latency and cost both look excellent.",
        "correct_path": "Route by difficulty instead of downgrading everything.",
        "backends": ("local", "ollama", "google"),
        "round": "trap",
    },
}

# Not injectable as a benchmark signature, and kept out of the timed session.
#   coldstart  -- needs a genuinely cold Cloud Run instance and a dedicated slot;
#                 its signature lives in the Cloud-Run-minus-app residual, which
#                 requires Cloud Monitoring (a later phase).
#   deployment -- an unhealthy revision produces zero successful requests. The
#                 report already refuses to score that. It is a facilitator
#                 preflight drill, not a teaching incident under time pressure.
DEFERRED = ("coldstart", "deployment")


# Pairs that are SUPPOSED to look identical to the benchmark.
#
# "Green dashboards" and "the cheap-model shortcut" both present as a fast,
# cheap, entirely healthy-looking service. That is not a flaw in the catalog --
# it is the lesson: infrastructure metrics cannot see a quality regression, and
# the only instrument that can is the eval. Declaring the pair here keeps the
# collision check strict for every other pair while stating, in one place, why
# this one is allowed. They separate on the eval:
#
#   staleness   a stale cache serves the wrong answer to anything, so BOTH
#               extraction and reasoning fail
#   cheapmodel  a small model still copies a fact out of a retrieved chunk, so
#               extraction holds (83%) and only reasoning collapses (67%)
#
# Verified by facilitators/eval_all.py, not by this script.
# `title` is the facilitator's name for the fault and several of them give the
# answer away -- "The new vector store" tells a participant exactly where to
# look. `public_title` is what a user would call it: the symptom, not the cause.
# Only public_title travels to the deployment.
QUALITY_SEPARATED = frozenset({frozenset({"staleness", "cheapmodel"})})


def env_for(name: str) -> dict:
    if name not in INCIDENTS:
        raise KeyError(f"unknown incident {name!r}; have {sorted(INCIDENTS)}")
    return dict(INCIDENTS[name]["env"])


def for_backend(backend: str) -> list[str]:
    """Incidents this backend can actually produce."""
    return [k for k, v in INCIDENTS.items() if backend in v["backends"]]
