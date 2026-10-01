"""Repair-history retrieval: "what happened the last times this kind of fault occurred?"

A tool-down arrives with a free-text symptom. We embed it and search a vector index of
past repairs (Qdrant) for the nearest neighbours on the same tool family. That gives:

* a **duration prediction**: similarity-weighted mean of the neighbours' actual repair
  times, with a p10-p90 range. This is k-nearest-neighbour regression, i.e. the brief's
  "ML-based" option done in a way that can be explained.
* **who has fixed this before**: engineers ranked by how many of the neighbours they fixed.
* the **likely root cause and fix** to brief the engineer with.

Runs with no key and no server by default: Qdrant in embedded mode (``:memory:`` in tests,
a local path otherwise) and a dependency-free hashed n-gram embedder. In production set
``FAB_QDRANT_URL`` (and ``FAB_QDRANT_API_KEY``) for a Qdrant server. The history is
synthetic but structured: each fault code has root causes with their own duration
distributions, so retrieval has real signal to find.
"""
from __future__ import annotations

import hashlib
import itertools
import math
import random
import re
import statistics
import threading
from dataclasses import dataclass

from .config import Settings

# family -> fault code -> (symptom phrasings, [(root cause, fix, mean minutes, sd)])
CATALOG: dict[str, dict[str, tuple[list[str], list[tuple[str, str, int, int]]]]] = {
    "litho": {
        "OVL-DRIFT": (["overlay drift out of spec", "alignment residuals trending high", "overlay excursion after reticle change"],
                      [("lens heating model stale", "recalibrate lens heating correction", 70, 15),
                       ("wafer stage interferometer drift", "re-zero interferometers and requalify stage", 150, 30)]),
        "FOCUS-ERR": (["focus spot defects on edge dies", "leveling sensor error", "best focus shifted"],
                      [("contaminated wafer chuck", "clean chuck and run flatness check", 90, 20),
                       ("leveling sensor out of calibration", "calibrate level sensor", 60, 10)]),
        "SRC-PWR": (["light source power unstable", "dose error alarm", "laser energy fluctuating"],
                    [("laser chamber gas aged", "laser gas refill and energy recal", 120, 25),
                     ("beam delivery optics degraded", "inspect and swap beam delivery optic", 200, 40)]),
    },
    "etch": {
        "RF-REFL": (["RF reflected power high", "plasma will not strike", "matching network fault"],
                    [("match network capacitor worn", "replace tuning capacitor", 80, 15),
                     ("RF cable connector damaged", "replace RF cable", 45, 10)]),
        "ESC-HE": (["chuck helium leak rate high", "wafer clamping failure", "backside helium flow alarm"],
                   [("ESC surface worn", "swap electrostatic chuck", 180, 30),
                    ("o-ring degraded", "replace helium o-ring", 60, 12)]),
        "PART-ADD": (["particle adders on monitor wafer", "defect density spike after etch", "flaking from chamber walls"],
                     [("chamber needs wet clean", "wet clean chamber and season", 240, 40),
                      ("process kit at end of life", "replace process kit", 120, 20)]),
    },
    "deposition": {
        "THK-NU": (["film thickness non-uniformity", "deposition rate drift", "center to edge thickness delta"],
                   [("showerhead holes clogged", "replace showerhead", 150, 30),
                    ("heater zone thermocouple drift", "recalibrate heater zones", 70, 15)]),
        "VAC-LEAK": (["base pressure too high", "chamber leak check failed", "pump down too slow"],
                     [("gate valve seal leaking", "replace gate valve seal", 90, 20),
                      ("turbo pump bearing worn", "swap turbo pump", 160, 30)]),
        "TGT-LIFE": (["sputter target near end of life", "arcing during PVD", "target voltage unstable"],
                     [("target eroded", "replace sputter target", 200, 35),
                      ("magnet assembly misaligned", "realign magnetron", 100, 20)]),
    },
    "cmp": {
        "PAD-WEAR": (["removal rate dropping", "pad life limit reached", "polish rate unstable"],
                     [("pad glazed", "replace pad and condition", 75, 15),
                      ("conditioner disk worn", "replace conditioner disk", 55, 10)]),
        "SLURRY": (["slurry flow alarm", "scratches on wafers after polish", "slurry delivery pressure low"],
                   [("slurry filter clogged", "change slurry filter and flush", 50, 10),
                    ("delivery pump diaphragm failed", "replace slurry pump", 130, 25)]),
        "HEAD-VAC": (["wafer slip out of carrier head", "head vacuum fault", "carrier membrane leak"],
                     [("membrane torn", "replace carrier membrane", 90, 15),
                      ("retaining ring worn", "replace retaining ring", 70, 12)]),
    },
    "implant": {
        "BEAM-CUR": (["beam current low", "beam tuning fails", "source arc unstable"],
                     [("ion source filament worn", "replace source filament", 110, 20),
                      ("extraction electrode coated", "clean extraction electrodes", 150, 30)]),
        "DOSE-UNI": (["dose uniformity out of spec", "scan uniformity alarm", "faraday cup reading erratic"],
                     [("faraday cup contaminated", "clean and recalibrate faraday", 80, 15),
                      ("scan waveform drift", "retune scan waveform", 60, 10)]),
    },
    "metrology": {
        "CAL-DRIFT": (["measurement drift on reference wafer", "gauge R&R failed", "calibration out of tolerance"],
                      [("reference standard degraded", "requalify with new standard", 45, 10),
                       ("stage encoder drift", "recalibrate stage", 70, 15)]),
        "OPT-FAULT": (["image focus failing on CD-SEM", "optical path alarm", "low signal to noise"],
                      [("electron gun tip aging", "condition or swap gun tip", 140, 25),
                       ("lamp at end of life", "replace light source lamp", 40, 8)]),
    },
}
PM_TASKS = {
    "litho": "scheduled scanner PM: lens and stage checks",
    "etch": "scheduled chamber PM: wet clean and process kit",
    "deposition": "scheduled chamber PM: shield kit and showerhead",
    "cmp": "scheduled polisher PM: pad, conditioner and slurry lines",
    "implant": "scheduled implanter PM: source rebuild",
    "metrology": "scheduled metrology PM: calibration and standards",
}

HISTORY_SIZE = 1800
HISTORY_SEED = 2026
DIM = 512


def fault_symptom(rng: random.Random, family: str) -> tuple[str, str, int]:
    """A fresh tool-down: (fault code, symptom text, planner's standard estimate in min)."""
    code = rng.choice(list(CATALOG[family]))
    phrases, causes = CATALOG[family][code]
    text = rng.choice(phrases) + rng.choice(["", " on chamber B", " after PM", " during production lot", " intermittently"])
    standard = round(statistics.fmean(c[2] for c in causes) / 15) * 15
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


def synthetic_history(n: int = HISTORY_SIZE, seed: int = HISTORY_SEED) -> list[Repair]:
    rng = random.Random(seed)
    engineers = [f"E{i:02d}" for i in range(1, 31)]
    out = []
    for i in range(n):
        family = rng.choice(list(CATALOG))
        code = rng.choice(list(CATALOG[family]))
        phrases, causes = CATALOG[family][code]
        cause, fix, mean, sd = rng.choice(causes)
        symptom = rng.choice(phrases) + rng.choice(["", " on chamber A", " on chamber B", " after PM", " during production lot"])
        # Some engineers are their family's go-to people: bias who fixed what.
        home = list(CATALOG).index(family) * 5   # stable across processes, unlike hash()
        eng = engineers[(home + rng.choice([0, 0, 1, 2, rng.randrange(30)])) % 30]
        out.append(Repair(i + 1, family, code, symptom, cause, fix,
                          max(15, int(rng.gauss(mean, sd))), eng))
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
            feats += [padded[i:i + 3] for i in range(len(padded) - 2)]
        for f in feats:
            h = int.from_bytes(hashlib.blake2b(f.encode(), digest_size=8).digest(), "little")
            vec[h % DIM] += 1.0 if (h >> 63) == 0 else -1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


class RepairIndex:
    COLLECTION = "repairs"

    def __init__(self, settings: Settings):
        from qdrant_client import QdrantClient  # lazy: keeps cold starts lean when unused

        if settings.qdrant_url:
            self.client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key, timeout=10)
            self.mode = "server"
        elif settings.env == "test":
            self.client = QdrantClient(":memory:")
            self.mode = "memory"
        else:
            self.client = QdrantClient(path=settings.qdrant_path)
            self.mode = "embedded"
        self.embedder = HashEmbedder()
        self._ready = False
        self._lock = threading.Lock()

    def ensure(self) -> None:
        """Build the index once (idempotent; skipped if a matching collection exists)."""
        if self._ready:
            return
        with self._lock:
            if self._ready:
                return
            from qdrant_client import models

            history = synthetic_history()
            if self.client.collection_exists(self.COLLECTION):
                if self.client.count(self.COLLECTION).count == len(history):
                    self._ready = True
                    return
                self.client.delete_collection(self.COLLECTION)
            self.client.create_collection(self.COLLECTION, vectors_config=models.VectorParams(
                size=DIM, distance=models.Distance.COSINE))
            self.client.create_payload_index(self.COLLECTION, "family", models.PayloadSchemaType.KEYWORD) \
                if self.mode == "server" else None
            batch = [models.PointStruct(id=r.id, vector=self.embedder.embed(r.symptom), payload=r.__dict__)
                     for r in history]
            for i in range(0, len(batch), 256):
                self.client.upsert(self.COLLECTION, points=batch[i:i + 256], wait=True)
            self._ready = True

    def similar(self, family: str, symptom: str, k: int = 12) -> dict:
        from qdrant_client import models

        self.ensure()
        hits = self.client.query_points(
            self.COLLECTION, query=self.embedder.embed(symptom), limit=k, with_payload=True,
            query_filter=models.Filter(must=[models.FieldCondition(key="family", match=models.MatchValue(value=family))]),
        ).points
        if not hits:
            return {"neighbours": [], "prediction": None}
        weights = [max(h.score, 0.0) ** 2 for h in hits]
        minutes = [h.payload["minutes"] for h in hits]
        total = sum(weights) or 1.0
        mean = sum(w * m for w, m in zip(weights, minutes, strict=True)) / total
        q = statistics.quantiles(minutes, n=10) if len(minutes) >= 2 else [minutes[0]] * 9
        causes: dict[str, float] = {}
        engineers: dict[str, int] = {}
        for h, w in zip(hits, weights, strict=True):
            causes[h.payload["cause"]] = causes.get(h.payload["cause"], 0) + w
            engineers[h.payload["engineer"]] = engineers.get(h.payload["engineer"], 0) + 1
        top_cause = max(causes, key=causes.get)
        return {
            "prediction": {
                "minutes": round(mean), "p10": round(q[0]), "p90": round(q[-1]),
                "confidence": round(statistics.fmean(h.score for h in hits[:5]), 3),
                "likely_cause": top_cause, "cause_share": round(causes[top_cause] / total, 2),
            },
            "experienced_engineers": sorted(engineers.items(), key=lambda kv: -kv[1])[:5],
            "neighbours": [{"score": round(h.score, 3), **{k: h.payload[k] for k in
                            ("id", "code", "symptom", "cause", "fix", "minutes", "engineer")}} for h in hits[:6]],
            "index": {"mode": self.mode, "embedder": self.embedder.name, "size": HISTORY_SIZE},
        }
