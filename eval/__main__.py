"""CLI: python -m eval [--limit N] [--model …] [--out path]."""

from __future__ import annotations

import argparse
from pathlib import Path

from backend.settings.config import MODEL_EVAL, OUTPUTS_DIR
from eval.runner import print_report_summary, run_eval


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run extraction eval against tenant invoices (5 companies × 5 docs)."
    )
    parser.add_argument("--limit", type=int, default=None, help="Max docs to eval")
    parser.add_argument("--model", default=MODEL_EVAL)
    parser.add_argument("--out", type=Path, default=OUTPUTS_DIR / "eval_report.json")
    args = parser.parse_args()

    report = run_eval(limit=args.limit, model=args.model, out=args.out)
    print_report_summary(report, args.out)


if __name__ == "__main__":
    main()
