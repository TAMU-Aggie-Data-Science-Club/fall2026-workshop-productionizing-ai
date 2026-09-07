# Failure Playbook

**Not for participants.** Read this before the session, not during it.

---

## Codespaces will not start / org policy blocks it

Fall back to local: `git clone`, `make setup`, `make serve`. It is the same
three commands. `make setup` takes a few minutes the first time, which is why
the prereq doc asks people to run it at home.

## `make setup` fails on a laptop

Most common cause is Python older than 3.10. Check with `python3 --version`.
Second most common is a corporate proxy blocking the PyTorch CPU index — put
them in Codespaces or on a spare laptop and move on. **Do not debug pip in front
of the room.**

## `make serve` starts but the first request hangs

The models load before the server accepts traffic, so if you see "Nimbus ready"
it is loaded. A first request that takes 5–10 seconds is normal on a 2-core
machine. That is the point of the exercise.

## Every benchmark request fails

The report will say so explicitly and tell them to check `make serve` is running.
Usual cause: benchmarking a different port than the server is on, or reloading
the configuration mid-run. Run `make reload`, wait for it to finish, then start
the next benchmark.

## The room is too slow — runs are taking too long

Cut the request count: `make bench ARGS="--requests 8"`. Numbers get noisier but
every lesson still lands. Say out loud that you are trading precision for time —
that is itself an honest engineering trade.

## Wifi dies completely

Use [`benchmark/paper_track.md`](../archive/paper_track.md). Tables can
diagnose the incident and make the same configuration decisions from its fixed
dashboard snapshots, then check the eval card. **This is a degraded session,
not a cancelled one.**

## Someone challenges the numbers

They are right to. The token prices, the request volume and the eval scores are
**illustrative and frozen** — say so plainly on the slide and out loud. The
latency and queueing numbers, however, are real measurements from their own
machine, and that is the part the activity turns on.

## A table finishes in five minutes

Give them the curveball: `make bench ARGS="--concurrency 16 --requests 32"`, and
ask whether their configuration still passes. Then ask them to get there while
using *fewer* levers than they did the first time.
