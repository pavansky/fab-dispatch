"""Assistant evaluation report (Markdown), published in every CI run's summary.

    python -m scripts.eval_report

Retrieval accuracy on the evaluation set, refusals of off-topic questions, and the score gap the
refusal threshold sits in. The pass/fail bar itself is enforced by tests/test_assistant.py.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.assistant.agent import MIN_DOC_SCORE
from app.assistant.index import get_index

EVAL = Path(__file__).resolve().parents[1] / "tests" / "eval" / "assistant_eval.json"


def main() -> None:
    data = json.loads(EVAL.read_text())
    index = get_index()
    hits, misses, answerable = 0, [], []
    for case in data["docs"]:
        expected = case["cite"] if isinstance(case["cite"], list) else [case["cite"]]
        top = index.search(case["q"], k=1)[0]
        answerable.append(top.score)
        if top.slug in expected and top.score >= MIN_DOC_SCORE:
            hits += 1
        else:
            misses.append((case["q"], ", ".join(expected), top.slug, top.score))
    off = [(q, (index.search(q, k=1) or [None])[0]) for q in data["refuse"]]
    off_scores = [h.score if h else 0.0 for _, h in off]
    refused = sum(s < MIN_DOC_SCORE for s in off_scores)
    n, m = len(data["docs"]), len(data["refuse"])
    print("## Assistant evaluation\n")
    print("| Measure | Result |\n|---|---|")
    print(f"| Right article cited | **{hits} / {n}** ({hits / n:.0%}) |")
    print(f"| Off-topic questions declined | **{refused} / {m}** |")
    print(f"| Lowest answerable score | {min(answerable):.2f} |")
    print(f"| Highest off-topic score | {max(off_scores):.2f} |")
    print(f"| Refusal threshold | {MIN_DOC_SCORE} |")
    if misses:
        print("\n### Misses\n\n| Question | Expected | Got | Score |\n|---|---|---|---|")
        for q, exp, got, score in misses:
            print(f"| {q} | {exp} | {got} | {score:.2f} |")


if __name__ == "__main__":
    main()
