"""
KavionLens360 pipeline runner (spec 9: manual ordered refresh, v1).

    python run_pipeline.py              # full run
    python run_pipeline.py --from 03    # resume from a SQL step (staging already loaded)

Order: schema -> load -> clean -> model -> customer_360 -> DQ checks
       -> Python segmentation + opportunity -> publish (exports) -> SQL questions.
"""
import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from c360 import db  # noqa: E402
from c360.load import load_staging  # noqa: E402

SQL_STEPS = [
    "00_schema.sql",
    "01_location_map.sql",
    "LOAD",
    "02_clean.sql",
    "03_model.sql",
    "04_customer_360.sql",
    "05_dq_checks.sql",
    "PYTHON",
    "06_publish.sql",
    "EXPORT",
]


def step_code(step: str) -> str:
    return step[:2] if step[:2].isdigit() else step


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", default=None,
                    help="start at this step code (e.g. 03, PYTHON, EXPORT)")
    ap.add_argument("--to", dest="stop", default=None, help="stop after this step code")
    args = ap.parse_args()

    run_id = datetime.now().strftime("run_%Y%m%d_%H%M%S")
    codes = [step_code(s) for s in SQL_STEPS]
    first = codes.index(args.start) if args.start else 0
    last = codes.index(args.stop) if args.stop else len(SQL_STEPS) - 1

    print(f"[{run_id}] steps {codes[first]} .. {codes[last]}")
    t0 = time.perf_counter()
    for step in SQL_STEPS[first:last + 1]:
        s = time.perf_counter()
        if step == "LOAD":
            rows = load_staging(run_id)
            print(f"  LOAD  staged {rows:,} rows", end="")
        elif step == "PYTHON":
            from c360 import segmentation, opportunity
            segmentation.run(run_id)
            opportunity.run(run_id)
            print("  PYTHON segmentation + opportunity scoring", end="")
        elif step == "EXPORT":
            from c360 import export
            export.run()
            print("  EXPORT aggregated extracts written", end="")
        else:
            db.run_sql_file(step)
            print(f"  {step}", end="")
        print(f"  ({time.perf_counter() - s:.1f}s)")
    print(f"done in {time.perf_counter() - t0:.1f}s")


if __name__ == "__main__":
    main()
