"""
Main pipeline orchestrator. Called by the web app or directly via CLI.

Usage:
  python run_pipeline.py [--steps 1,2,3,4,5,6,7]
                         [--preview]
                         [--asset sax1] [--locale en] [--aspect 16x9] [--model kling]
                         [--dry-run]
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent


def log(msg: str):
    print(msg, flush=True)


def load_config() -> dict:
    return json.loads((ROOT / "config.json").read_text())


def run_step(step: int, args: argparse.Namespace, cfg: dict):
    if step == 1:
        log("── Step 1: Parsing brief and matching assets ──")
        from pipeline.step_01_parse_brief import run
        run(cfg, dry_run=args.dry_run)

    elif step == 2:
        log("── Step 2: Generating copy for all locales ──")
        from pipeline.step_02_generate_copy import run
        run(cfg, dry_run=args.dry_run)

    elif step == 3:
        log("── Step 3: Generating backgrounds (Stage 1 image → Stage 2 video) ──")
        from pipeline.step_03_generate_backgrounds import run
        run(
            cfg,
            preview=args.preview,
            filter_asset=args.asset,
            filter_locale=args.locale,
            filter_aspect=args.aspect,
            filter_model=args.model,
            dry_run=args.dry_run,
        )

    elif step == 4:
        log("── Step 4: Building output AEP ──")
        from pipeline.step_04_build_output_aep import run
        run(cfg, dry_run=args.dry_run)

    elif step == 5:
        log("── Step 5: Batch rendering via nexrender / aerender ──")
        from pipeline.step_05_render import run
        run(cfg, dry_run=args.dry_run)

    elif step == 6:
        log("── Step 6: Generating Google Sheets tracking matrix ──")
        from pipeline.step_06_tracking_sheet import run
        run(cfg, dry_run=args.dry_run)

    elif step == 7:
        log("── Step 7: Delivering to Google Drive ──")
        from pipeline.step_07_deliver import run
        run(cfg, dry_run=args.dry_run)


def main():
    parser = argparse.ArgumentParser(description="Yosuki pipeline orchestrator")
    parser.add_argument("--steps", default="1,2,3,4,5", help="Comma-separated steps to run")
    parser.add_argument("--preview", action="store_true", help="Run step 3 in preview mode (one asset)")
    parser.add_argument("--asset",  default=None, help="Filter by asset name (e.g. sax1)")
    parser.add_argument("--locale", default=None, help="Filter by locale (e.g. en)")
    parser.add_argument("--aspect", default=None, help="Filter by aspect ratio (e.g. 16x9)")
    parser.add_argument("--model",  default=None, help="Override video model for regeneration")
    parser.add_argument("--dry-run", action="store_true", help="Validate inputs only; make no API calls")
    args = parser.parse_args()

    cfg = load_config()
    steps = [int(s.strip()) for s in args.steps.split(",")]

    if args.dry_run:
        log("DRY RUN — no API calls will be made")

    for step in steps:
        try:
            run_step(step, args, cfg)
        except Exception as exc:
            log(f"ERROR in step {step}: {exc}")
            sys.exit(1)

    log("Pipeline complete.")


if __name__ == "__main__":
    main()
