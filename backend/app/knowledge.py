"""Repair-history retrieval: "what happened the last times this kind of fault occurred?"

A tool-down arrives with a free-text symptom. Each fab's fault catalogue lives in its
profile (app/fabs/profiles), and each fab gets its own history and its own index. We embed it and search a vector index of
past repairs (Qdrant) for the nearest neighbours on the same tool family. That gives:

* a **duration prediction**: similarity-weighted mean of the neighbours' actual repair
  times, with a p10-p90 range. This is k-nearest-neighbour regression, i.e. the brief's
  "ML-based" option done in a way that can be explained.
* **who has fixed this before**: engineers ranked by how many of the neighbours they fixed.
* the **likely root cause and fix** to brief the engineer with.

Runs with no key and no server by default: an exact cosine search in NumPy over a
dependency-free hashed n-gram embedding. At 1,800 repairs per fab that is one ~1 ms matrix
product, so a vector database would only add a dependency and cold-start time. Real repair
history grows into the millions; set ``FAB_QDRANT_URL`` (and ``FAB_QDRANT_API_KEY``) and the
same interface runs on a Qdrant server with approximate (HNSW) search. ``FAB_QDRANT_PATH``
keeps an embedded on-disk Qdrant for local experiments. The history is
synthetic but structured: each fault code has root causes with their own duration
distributions, so retrieval has real signal to find.
"""

from __future__ import annotations

import hashlib
import itertools
import logging
import math
import random
import re
import statistics
import threading
from dataclasses import dataclass

import numpy as np

from .config import Settings
from .fabs import FabProfile

log = logging.getLogger("fab")

HISTORY_SIZE = 1800
HISTORY_SEED = 2026
DIM = 512


def fault_symptom(rng: random.Random, profile: FabProfile, family: str) -> tuple[str, str, int]:
    """A fresh tool-down: (fault code, symptom text, planner's standard estimate in min)."""
    faults = profile.family(family).faults
    code = rng.choice(list(faults))
    fault = faults[code]
    text = rng.choice(fault.symptoms) + rng.choice(
        ["", " on chamber B", " after PM", " during production lot", " intermittently"]
    )
    standard = round(statistics.fmean(c.mean_min for c in fault.causes) / 15) * 15
    return code, text, int(standard)


@dataclass(frozen=True)
class Repair:
    id: int
    family: str
    code: str
    symptom: str
    cause: str
    fix: str
    minutes: int
    engineer: str


def synthetic_history(profile: FabProfile, n: int = HISTORY_SIZE, seed: int = HISTORY_SEED) -> list[Repair]:
    """A fab's past repairs, generated from its own fault catalogue (deterministic)."""
    rng = random.Random(seed)
    engineers = [f"E{i:02d}" for i in range(1, 31)]
    families = profile.family_ids
    out = []
    for i in range(n):
        family = rng.choice(families)
        faults = profile.family(family).faults
        code = rng.choice(list(faults))
        fault = faults[code]
        c = rng.choice(fault.causes)
        cause, fix, mean, sd = c.cause, c.fix, c.mean_min, c.sd_min
        symptom = rng.choice(fault.symptoms) + rng.choice(
            ["", " on chamber A", " on chamber B", " after PM", " during production lot"]
        )
        # Some engineers are their family's go-to people: bias who fixed what.
        home = families.index(family) * 5  # stable across processes, unlike hash()
        eng = engineers[(home + rng.choice([0, 0, 1, 2, rng.randrange(30)])) % 30]
        out.append(Repair(i + 1, family, code, symptom, cause, fix, max(15, int(rng.gauss(mean, sd))), eng))
    return out


class HashEmbedder:
    """Dependency-free text embedding: hashed word and character-trigram features, L2
    normalised. Captures lexical similarity, which suits short technical symptom text.
    Swap for a neural model (e.g. fastembed) with no other change."""

    name = "hashed-ngrams-512"

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * DIM
        words = re.findall(r"[a-z0-9]+", text.lower())
        feats = words + [f"{a}_{b}" for a, b in itertools.pairwise(words)]
        for w in words:
            padded = f"#{w}#"
            feats += [padded[i : i + 3] for i in range(len(padded) - 2)]
        for f in feats:
            h = int.from_bytes(hashlib.blake2b(f.encode(), digest_size=8).digest(), "little")
            vec[h % DIM] += 1.0 if (h >> 63) == 0 else -1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


class _ExactIndex:
    """Exact cosine k-NN in NumPy: vectors are L2-normalised, so cosine is a dot product."""

    mode = "exact"

    def __init__(self, embedder: HashEmbedder):
        self.embedder = embedder
        self._fabs: dict[str, tuple[np.ndarray, np.ndarray, list[dict]]] = {}
        self._lock = threading.Lock()

    def ensure(self, profile: FabProfile) -> None:
        if profile.id in self._fabs:
            return
        with self._lock:
            if profile.id in self._fabs:
                return
            history = synthetic_history(profile)
            vectors = np.array([self.embedder.embed(r.symptom) for r in history], dtype=np.float32)
            families = np.array([r.family for r in history])
            self._fabs[profile.id] = (vectors, families, [r.__dict__ for r in history])

    def search(self, profile: FabProfile, family: str, symptom: str, k: int) -> list[tuple[float, dict]]:
        self.ensure(profile)
        vectors, families, payloads = self._fabs[profile.id]
        rows = np.flatnonzero(families == family)
        if rows.size == 0:
            return []
        scores = vectors[rows] @ np.array(self.embedder.embed(symptom), dtype=np.float32)
        top = np.argsort(-scores, kind="stable")[:k]
        return [(float(scores[i]), payloads[rows[i]]) for i in top]


class _QdrantIndex:
    """One Qdrant collection per fab (``repairs_<fab id>``), built lazily on first use."""

    def __init__(self, settings: Settings, embedder: HashEmbedder):
        from qdrant_client import QdrantClient  # lazy: only loaded when a Qdrant mode is configured

        if settings.qdrant_url:
            self.client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key, timeout=10)
            self.mode = "qdrant-server"
        else:
            # On-disk embedded mode takes an exclusive lock on the folder, so a second process
            # (reloader, extra worker) can't open it. The history is deterministic and rebuilds
            # in under a second, so fall back to memory rather than fail the request.
            try:
                self.client = QdrantClient(path=settings.qdrant_path)
                self.mode = "qdrant-disk"
            except RuntimeError as e:
                log.warning("qdrant path %s unavailable (%s); using in-memory index", settings.qdrant_path, e)
                self.client = QdrantClient(":memory:")
                self.mode = "qdrant-memory"
        self.embedder = embedder
        self._ready: set[str] = set()
        self._lock = threading.Lock()

    @staticmethod
    def collection(fab_id: str) -> str:
        return "repairs_" + fab_id.replace("-", "_")

    def ensure(self, profile: FabProfile) -> str:
        """Build this fab's index once (idempotent; skipped if a matching collection exists)."""
        name = self.collection(profile.id)
        if name in self._ready:
            return name
        with self._lock:
            if name in self._ready:
                return name
            from qdrant_client import models

            history = synthetic_history(profile)
            if self.client.collection_exists(name):
                if self.client.count(name).count == len(history):
                    self._ready.add(name)
                    return name
                self.client.delete_collection(name)
            self.client.create_collection(
                name, vectors_config=models.VectorParams(size=DIM, distance=models.Distance.COSINE)
            )
            if self.mode == "qdrant-server":
                self.client.create_payload_index(name, "family", models.PayloadSchemaType.KEYWORD)
            batch = [
                models.PointStruct(id=r.id, vector=self.embedder.embed(r.symptom), payload=r.__dict__) for r in history
            ]
            for i in range(0, len(batch), 256):
                self.client.upsert(name, points=batch[i : i + 256], wait=True)
            self._ready.add(name)
            return name

    def search(self, profile: FabProfile, family: str, symptom: str, k: int) -> list[tuple[float, dict]]:
        from qdrant_client import models

        name = self.ensure(profile)
        hits = self.client.query_points(
            name,
            query=self.embedder.embed(symptom),
            limit=k,
            with_payload=True,
            query_filter=models.Filter(
                must=[models.FieldCondition(key="family", match=models.MatchValue(value=family))]
            ),
        ).points
        return [(h.score, h.payload) for h in hits]


class RepairIndex:
    """k-NN over past repairs. Exact NumPy search by default; Qdrant when configured."""

    def __init__(self, settings: Settings):
        self.embedder = HashEmbedder()
        use_qdrant = settings.qdrant_url or (settings.qdrant_path and settings.env != "test")
        self.backend = _QdrantIndex(settings, self.embedder) if use_qdrant else _ExactIndex(self.embedder)

    @property
    def mode(self) -> str:
        return self.backend.mode

    def similar(self, profile: FabProfile, family: str, symptom: str, k: int = 12) -> dict:
        # A neighbour with no shared feature (score 0) says nothing about this fault.
        hits = [(score, p) for score, p in self.backend.search(profile, family, symptom, k) if score > 0]
        if not hits:
            return {"neighbours": [], "prediction": None}
        weights = [max(score, 0.0) ** 2 for score, _ in hits]
        minutes = [p["minutes"] for _, p in hits]
        total = sum(weights) or 1.0
        mean = sum(w * m for w, m in zip(weights, minutes, strict=True)) / total
        q = statistics.quantiles(minutes, n=10) if len(minutes) >= 2 else [minutes[0]] * 9
        causes: dict[str, float] = {}
        engineers: dict[str, int] = {}
        for (_, p), w in zip(hits, weights, strict=True):
            causes[p["cause"]] = causes.get(p["cause"], 0) + w
            engineers[p["engineer"]] = engineers.get(p["engineer"], 0) + 1
        top_cause = max(causes, key=causes.get)
        return {
            "prediction": {
                "minutes": round(mean),
                "p10": round(q[0]),
                "p90": round(q[-1]),
                "confidence": round(statistics.fmean(score for score, _ in hits[:5]), 3),
                "likely_cause": top_cause,
                "cause_share": round(causes[top_cause] / total, 2),
            },
            "experienced_engineers": sorted(engineers.items(), key=lambda kv: -kv[1])[:5],
            "neighbours": [
                {
                    "score": round(score, 3),
                    **{k: p[k] for k in ("id", "code", "symptom", "cause", "fix", "minutes", "engineer")},
                }
                for score, p in hits[:6]
            ],
            "index": {"mode": self.mode, "embedder": self.embedder.name, "size": HISTORY_SIZE},
        }
