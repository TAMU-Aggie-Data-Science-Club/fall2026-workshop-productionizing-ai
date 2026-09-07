"""Download every model weight at image build time.

A service that fetches weights on first request pays for it in the latency
numbers, and a room of thirty people fetching them simultaneously over venue
wifi is the single most likely way for this workshop to fail. Do it once, here.
"""
import os, sys, pathlib
# This is the sole code path allowed to fetch weights. The server itself runs
# offline so a venue-network hiccup cannot distort a benchmark or stall a room.
os.environ["NIMBUS_ALLOW_MODEL_DOWNLOAD"] = "1"
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "service"))

import model          # noqa: E402
import embed          # noqa: E402  (importing it downloads the embedder)

print("prefetching model tiers...")
model.warm()
print("prefetching embedding model...")
embed.embed_one("warm")
print("all weights cached.")
