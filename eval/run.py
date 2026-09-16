from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "DjangoForAI.settings")

import django

django.setup()

from eval.metrics import load_cases, score_prediction, summarize


def main() -> int:
    predictions_path = Path(os.environ.get("EVAL_PREDICTIONS", ""))
    predictions = {}
    if predictions_path.is_file():
        predictions = json.loads(predictions_path.read_text())

    results = []
    for case in load_cases():
        if predictions:
            pred = predictions.get(case["id"], {})
            sql = pred.get("sql")
            refused = bool(pred.get("refused", case.get("must_refuse") and sql is None))
            linked = pred.get("linked_tables")
        else:
            refused = bool(case.get("must_refuse"))
            sql = None if refused else case.get("gold_sql")
            linked = case.get("gold_tables")
        results.append(
            score_prediction(
                case,
                sql=sql,
                refused=refused,
                linked_tables=linked,
            )
        )

    if os.environ.get("EVAL_LIVE") == "1":
        print("EVAL_LIVE graph execution is opt-in and requires a running workspace.")

    summary = summarize(results)
    print(json.dumps({"summary": summary, "results": results}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
