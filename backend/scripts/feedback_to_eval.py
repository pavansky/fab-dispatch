"""Export unhelpful assistant answers as candidate evaluation cases.

    cd backend && python -m scripts.feedback_to_eval [--days 30] [--out candidates.json]

Reads the thumbs-down ratings that carry a comment (``POST /api/assistant/feedback``) from the
default database and writes them in the format of ``tests/eval/assistant_eval.json``, so the
loop "poor answers become new evaluation cases" is a command, not a promise:

* a rating on a **refusal** (intent ``unknown``) is a question the assistant should perhaps
  have answered: it lands under ``docs`` with an empty ``cite`` for a reviewer to fill in;
* a rating on a **cited answer** lands under ``docs`` too, with the slugs that were cited in
  ``_was_cited``: the reviewer decides whether the right article is another one (set ``cite``)
  or the question was out of scope (move it to ``refuse``).

Every case keeps the reviewer's context in underscore fields (``_comment``, ``_intent``,
``_votes``), which the test ignores. No user ids are exported. Review the file, then move the
cases you keep into ``tests/eval/assistant_eval.json``; CI runs them from then on.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def candidates(rows: list[dict]) -> dict:
    """Group thumbs-down ratings with a comment by question; most-voted first."""
    by_question: dict[str, dict] = {}
    for r in rows:
        if r.get("helpful") or not (r.get("comment") or "").strip():
            continue
        q = r["question"].strip()
        case = by_question.setdefault(
            q, {"q": q, "cite": [], "_was_cited": [], "_intent": r["intent"], "_comment": [], "_votes": 0}
        )
        case["_votes"] += 1
        case["_comment"].append(r["comment"].strip())
        for slug in r.get("citations") or []:
            if slug not in case["_was_cited"]:
                case["_was_cited"].append(slug)
    docs = sorted(by_question.values(), key=lambda c: (-c["_votes"], c["q"]))
    for c in docs:
        c["_comment"] = " | ".join(dict.fromkeys(c["_comment"]))
    return {
        "_about": (
            "Candidate evaluation cases from thumbs-down ratings with a comment. Review each one: set 'cite' to "
            "the article that should answer it (or move it to 'refuse' if it is out of scope), drop the "
            "underscore fields, and add it to tests/eval/assistant_eval.json."
        ),
        "docs": docs,
        "refuse": [],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--days", type=int, default=30, help="look back this many days (default 30)")
    ap.add_argument("--out", type=Path, default=None, help="write here instead of stdout")
    args = ap.parse_args(argv)
    from app.deps import get_store

    rows = get_store().recent_feedback(days=args.days, helpful=False)
    out = candidates(rows)
    text = json.dumps(out, indent=2, ensure_ascii=False) + "\n"
    if args.out:
        args.out.write_text(text)
        print(f"wrote {len(out['docs'])} candidate case(s) to {args.out}", file=sys.stderr)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
