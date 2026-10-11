"""Repair-history retrieval: "what happened the last times this kind of fault occurred?"

A tool-down arrives with a free-text symptom. Each fab's fault catalogue lives in its
profile (app/fabs/profiles), and each fab gets its own history and its own index. We embed
the symptom and search a vector index of past repairs for the nearest neighbours on the same
tool family. That gives:

* a **duration estimate**: the similarity-weighted mean of the neighbours' actual repair
  times (k-nearest-neighbour regression, explained by showing the neighbours), with the P10
  and P90 of those neighbours' times. P10-P90 is the middle 80% of the neighbours, so roughly
  8 in 10 repairs land inside it; it is not a 90% interval. About 9 in 10 finish by the P90.
  ``scripts/duration_study.py`` measures both on held-out repairs.
* **who has fixed this before**: engineers ranked by how many of the neighbours they fixed,
  limited to the people on shift when the caller passes a roster. History and shifts share
  engineer ids (E01, E02, ...).
* the **likely root cause and fix** to brief the engineer with: the cause with the largest
  similarity-weighted share of the neighbours. ``cause_share`` is that share and
  ``confidence`` is the mean cosine similarity of the closest five neighbours (how close the
  matches are). Neither is a calibrated probability. ``match`` labels the confidence in words:
  ``close`` (>= ``CLOSE_SIMILARITY``) or ``partial``.

**Cold start.** A symptom that shares little with the history ("tool is down") still has
nearest neighbours, but they are different faults. When the best neighbour scores below
``MIN_SIMILARITY`` there is **no prediction**: the answer carries ``reason`` and the nearest
few records as ``weak_matches``, labelled as such, so a caller can show them without
presenting a guess as a forecast. On held-out generated repairs the best neighbour scores
0.78 or more; vague text scores 0.5 or less.

Runs with no key and no server by default: an exact cosine search in NumPy over a
dependency-free hashed n-gram embedding. At 1,800 repairs per fab that is one ~1 ms matrix
product, so a vector database would only add a dependency and cold-start time. Real repair
history grows into the millions; set ``FAB_QDRANT_URL`` (and ``FAB_QDRANT_API_KEY``) and the
same interface runs on a Qdrant server with approximate (HNSW) search. ``FAB_QDRANT_PATH``
keeps an embedded on-disk Qdrant for local experiments.

**What signal the synthetic history carries.** Each fault code in the catalogue has root
causes (two per code in the shipped profiles), drawn with equal probability, each with its
own duration distribution. A report always has one of the code's generic symptoms plus a
context suffix ("after PM", "on chamber B"); neither depends on the cause. In
``OBSERVATION_RATE`` (60%) of reports the engineer also adds an observation that points to the
true cause, built from the catalogue text: ``"suspect <cause>"`` or ``"tech recommends:
<fix>"`` (:func:`cause_observations`). The other 40% say nothing about the cause. So the text
identifies the cause in at most about 60% + 40%/(causes per code) of reports (80% with two
causes), and a duration estimate can beat the fault code's mean only through those
observations. Live tool-downs (:func:`fault_symptom`, used by the shift generator) are drawn
the same way, so a live job's symptom carries the same partial signal.
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
from collections.abc import Collection
from dataclasses import astuple, dataclass

import numpy as np

from .config import Settings
from .fabs import FabProfile, FaultCause

log = logging.getLogger("fab")

HISTORY_SIZE = 1800
HISTORY_SEED = 2026
DIM = 512
OBSERVATION_RATE = 0.6  # share of reports with an observation that points to the root cause
MIN_SIMILARITY = 0.35  # best neighbour below this: no prediction, only weak matches
CLOSE_SIMILARITY = 0.7  # mean similarity of the closest five at or above this: a close match
WEAK_MATCHES = 3  # how many nearest records to show when there is no prediction


def cause_observations(cause: FaultCause) -> tuple[str, str]:
    """What an engineer may add to a report when this root cause is behind the fault: the
    suspected cause, or the fix they expect to need. Built from the catalogue text, so a new
    fab profile gets them with no extra data."""
    return f"suspect {cause.cause}", f"tech recommends: {cause.fix}"


def _report(rng: random.Random, generic: str, context: str, cause: FaultCause) -> str:
    """Symptom text: a generic symptom of the fault code, then sometimes a cause observation."""
    text = generic + context
    if rng.random() < OBSERVATION_RATE:
        text += "; " + rng.choice(cause_observations(cause))
    return text


def standard_estimate(profile: FabProfile, family: str, code: str) -> int:
    """The planner's standard estimate for a fault code: the catalogue mean over its root
    causes (the generator's true mean, as causes are equally likely), rounded to 15 min."""
    causes = profile.family(family).faults[code].causes
    return int(round(statistics.fmean(c.mean_min for c in causes) / 15) * 15)


def draw_fault(rng: random.Random, profile: FabProfile, family: str) -> tuple[str, FaultCause, str, int]:
    """A fresh tool-down: (fault code, latent root cause, symptom text, standard estimate).

    ``rng`` is advanced exactly as it was before symptoms carried a cause (code, generic
    symptom, context), so every other field of a generated shift is unchanged. The latent
    cause and the observation come from a generator seeded by ``rng``'s current state, which
    is deterministic and does not advance it."""
    faults = profile.family(family).faults
    code = rng.choice(list(faults))
    fault = faults[code]
    generic = rng.choice(fault.symptoms)
    context = rng.choice(["", " on chamber B", " after PM", " during production lot", " intermittently"])
    sub = random.Random(hashlib.blake2b(repr(rng.getstate()).encode(), digest_size=16).digest())
    cause = sub.choice(fault.causes)
    return code, cause, _report(sub, generic, context, cause), standard_estimate(profile, family, code)


def fault_symptom(rng: random.Random, profile: FabProfile, family: str) -> tuple[str, str, int]:
    """A fresh tool-down: (fault code, symptom text, planner's standard estimate in min).
    The text carries the same partial root-cause signal as the history (see the module doc)."""
    code, _, text, standard = draw_fault(rng, profile, family)
    return code, text, standard


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
    """A fab's past repairs, generated from its own fault catalogue (deterministic).

    Per repair: a family and fault code, a root cause (equally likely), a symptom that is a
    generic symptom of the code plus, in ``OBSERVATION_RATE`` of repairs, an observation
    pointing to the cause (module doc), and a duration drawn from that cause's distribution."""
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
        generic = rng.choice(fault.symptoms)
        context = rng.choice(["", " on chamber A", " on chamber B", " after PM", " during production lot"])
        symptom = _report(rng, generic, context, c)
        # Some engineers are their family's go-to people: bias who fixed what.
        home = families.index(family) * 5  # stable across processes, unlike hash()
        eng = engineers[(home + rng.choice([0, 0, 1, 2, rng.randrange(30)])) % 30]
        minutes = max(15, int(rng.gauss(c.mean_min, c.sd_min)))
        out.append(Repair(i + 1, family, code, symptom, c.cause, c.fix, minutes, eng))
    return out


def history_version(history: list[Repair], embedder: str) -> str:
    """Content hash of a generated history and the embedding it is indexed with: an edited
    fault catalogue (or a new embedder) gets a new version, so a stored index is rebuilt."""
    h = hashlib.sha256(f"{embedder}|{DIM}".encode())
    for r in history:
        h.update(repr(astuple(r)).encode())
    return h.hexdigest()[:12]


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
    """One Qdrant collection per fab and history version (``repairs_<fab id>_<version>``),
    built lazily on first use. The version is a content hash of the generated history, so
    editing a fab's fault catalogue builds a fresh collection instead of reusing a stale one
    that happens to have the same number of points. Older versions are left in place (a
    process still running the old catalogue may be reading them); drop them by hand."""

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
        self._ready: dict[str, str] = {}  # fab id -> collection name
        self._lock = threading.Lock()

    @staticmethod
    def collection(fab_id: str, version: str) -> str:
        return f"repairs_{fab_id.replace('-', '_')}_{version}"

    def ensure(self, profile: FabProfile) -> str:
        """Build this fab's index once (idempotent; skipped if this history version is stored)."""
        if profile.id in self._ready:
            return self._ready[profile.id]
        with self._lock:
            if profile.id in self._ready:
                return self._ready[profile.id]
            from qdrant_client import models

            history = synthetic_history(profile)
            name = self.collection(profile.id, history_version(history, self.embedder.name))
            if self.client.collection_exists(name):
                if self.client.count(name).count == len(history):  # a complete build of this version
                    self._ready[profile.id] = name
                    return name
                self.client.delete_collection(name)  # an interrupted build
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
            self._ready[profile.id] = name
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

    def similar(
        self, profile: FabProfile, family: str, symptom: str, k: int = 12, roster: Collection[str] | None = None
    ) -> dict:
        """The k most similar past repairs on this tool family and what they suggest (module
        doc). ``roster``: engineer ids on shift; when given, ``experienced_engineers`` lists
        only them (the history spans a larger pool than any one shift)."""
        # A neighbour with no shared feature (score 0) says nothing about this fault.
        hits = [(score, p) for score, p in self.backend.search(profile, family, symptom, k) if score > 0]
        index = {"mode": self.mode, "embedder": self.embedder.name, "size": HISTORY_SIZE}
        if not hits or hits[0][0] < MIN_SIMILARITY:
            # Cold start: the nearest records are different faults, so a weighted mean of their
            # times would be a guess dressed as a forecast. Show them only as weak matches.
            return {
                "prediction": None,
                "reason": "no similar repair history",
                "weak_matches": [self._record(score, p) for score, p in hits[:WEAK_MATCHES]],
                "experienced_engineers": [],
                "neighbours": [],
                "index": index,
            }
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
        if roster is not None:
            on_shift = set(roster)
            engineers = {e: n for e, n in engineers.items() if e in on_shift}
        top_cause = max(causes, key=causes.get)
        confidence = round(statistics.fmean(score for score, _ in hits[:5]), 3)
        return {
            "prediction": {
                "minutes": round(mean),
                "p10": round(q[0]),
                "p90": round(q[-1]),
                # Mean cosine similarity of the closest five: how close the matches are.
                "confidence": confidence,
                "match": "close" if confidence >= CLOSE_SIMILARITY else "partial",
                "likely_cause": top_cause,
                "cause_share": round(causes[top_cause] / total, 2),  # weighted share, not a probability
                "neighbours": len(hits),
                "basis": (
                    f"similarity-weighted mean of the {len(hits)} most similar past repairs; "
                    "p10-p90 spans the middle 80% of their actual times"
                ),
            },
            "experienced_engineers": sorted(engineers.items(), key=lambda kv: -kv[1])[:5],
            "neighbours": [self._record(score, p) for score, p in hits[:6]],
            "index": index,
        }

    @staticmethod
    def _record(score: float, p: dict) -> dict:
        return {
            "score": round(score, 3),
            **{k: p[k] for k in ("id", "code", "symptom", "cause", "fix", "minutes", "engineer")},
        }
