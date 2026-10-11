"""Assistant evaluation report (Markdown), published in every CI run's summary.

    python -m scripts.eval_report

Runs ``tests/eval/assistant_eval.json`` end to end through ``Assistant.ask()`` (the same path
``POST /api/assistant/ask`` takes, without a shift on screen): the right article must be the
first citation and the answer must not be a refusal; off-topic questions must be refused.
Also shows the retrieval scores the refusal threshold sits between. The pass/fail bar itself
is enforced by tests/test_assistant.py.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.assistant import AskContext, get_assistant
from app.assistant.agent import MIN_DOC_SCORE, off_task
from app.assistant.index import get_index

EVAL = Path(__file__).resolve().parents[1] / "tests" / "eval" / "assistant_eval.json"
ANSWERABLE = {"docs": "Right article cited (keyword phrasings)", "docs_hard": "Right article cited (paraphrases)"}
REFUSED = {"refuse": "Off-topic questions declined", "refuse_app_vocabulary": "Off-topic with app words declined"}


def main() -> None:
    data = json.loads(EVAL.read_text())
    assistant, index = get_assistant(), get_index()
    rows, misses, answerable, off_scores = [], [], [], []
    for group, label in ANSWERABLE.items():
        hits = 0
        for case in data[group]:
            expected = case["cite"] if isinstance(case["cite"], list) else [case["cite"]]
            a = assistant.ask(case["q"], AskContext())
            top = a.citations[0].slug if a.citations else "-"
            best = index.search(case["q"], k=1)
            answerable.append(best[0].score if best else 0.0)
            if a.intent != "unknown" and top in expected:
                hits += 1
            else:
                misses.append((case["q"], ", ".join(expected), f"{a.intent}: {top}", best[0].score if best else 0.0))
        rows.append((label, hits, len(data[group])))
    for group, label in REFUSED.items():
        refused = 0
        for q in data[group]:
            a = assistant.ask(q, AskContext())
            best = index.search(q, k=1)
            if not off_task(q):  # the others are refused by rule, whatever retrieval says
                off_scores.append(best[0].score if best else 0.0)
            if a.intent == "unknown":
                refused += 1
            else:
                misses.append(
                    (q, "refusal", f"{a.intent}: {a.citations[0].slug if a.citations else '-'}", best[0].score)
                )
        rows.append((label, refused, len(data[group])))
    total, n = sum(h for _, h, _ in rows), sum(c for _, _, c in rows)
    print("## Assistant evaluation\n")
    print("| Measure | Result |\n|---|---|")
    for label, hits, count in rows:
        print(f"| {label} | **{hits} / {count}** ({hits / count:.0%}) |")
    print(f"| All cases | **{total} / {n}** ({total / n:.0%}) |")
    print(f"| Lowest answerable retrieval score | {min(answerable):.2f} |")
    print(f"| Highest off-topic retrieval score (questions not caught by the off-task rule) | {max(off_scores):.2f} |")
    print(f"| Refusal threshold | {MIN_DOC_SCORE} |")
    if misses:
        print("\n### Misses\n\n| Question | Expected | Got | Retrieval score |\n|---|---|---|---|")
        for q, exp, got, score in misses:
            print(f"| {q} | {exp} | {got} | {score:.2f} |")


if __name__ == "__main__":
    main()
