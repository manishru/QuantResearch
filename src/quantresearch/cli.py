"""Command-line interface for infrastructure checks."""

from __future__ import annotations

import argparse
import json
import logging
import platform
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from quantresearch import __version__
from quantresearch.config import get_settings
from quantresearch.ingestion.component_csv import load_component_snapshots
from quantresearch.ingestion.review_decisions import (
    load_exclusion_decisions,
    load_mapping_decisions,
)
from quantresearch.logging_config import configure_logging
from quantresearch.storage.research_store import ResearchStore
from quantresearch.timing import Timer
from quantresearch.walkforward.windows import generate_walk_forward_windows


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="quantresearch", description="QuantResearch CLI")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="Verify project paths and runtime")
    doctor.add_argument("--json", action="store_true", help="Emit machine-readable JSON")

    universe = subparsers.add_parser("universe", help="Inspect point-in-time index membership")
    universe_commands = universe.add_subparsers(dest="universe_command", required=True)
    inspect = universe_commands.add_parser("inspect", help="Inspect a component snapshot file")
    inspect.add_argument("--input", type=Path, required=True, help="Complete snapshot CSV")
    inspect.add_argument("--index-id", required=True, help="Stable index identifier")
    inspect.add_argument("--as-of", type=date.fromisoformat, required=True, help="ISO date")
    inspect.add_argument("--json", action="store_true", help="Emit machine-readable JSON")

    research_db = subparsers.add_parser("research-db", help="Manage the research database")
    research_commands = research_db.add_subparsers(dest="research_command", required=True)
    for command, help_text in (
        ("init", "Initialize or migrate the research database"),
        ("inspect", "Inspect research database schema and row counts"),
    ):
        command_parser = research_commands.add_parser(command, help=help_text)
        command_parser.add_argument("--database", type=Path, help="DuckDB path")
        command_parser.add_argument("--json", action="store_true", help="Emit JSON")

    walk_forward = subparsers.add_parser("walk-forward", help="Manage walk-forward research")
    walk_commands = walk_forward.add_subparsers(dest="walk_command", required=True)
    schedule = walk_commands.add_parser("schedule", help="Preview canonical research windows")
    schedule.add_argument("--start-year", type=int, default=1996)
    schedule.add_argument("--last-completed-year", type=int, required=True)
    schedule.add_argument("--warmup-days", type=int, default=400)
    schedule.add_argument("--json", action="store_true", help="Emit JSON")

    review = subparsers.add_parser("review", help="Validate review decision artifacts")
    review_commands = review.add_subparsers(dest="review_command", required=True)
    validate = review_commands.add_parser("validate", help="Validate decision CSV files")
    validate.add_argument("--mappings", type=Path, help="Provider mapping decision CSV")
    validate.add_argument("--exclusions", type=Path, help="Exclusion decision CSV")
    validate.add_argument("--json", action="store_true", help="Emit JSON")
    return parser


def _doctor(as_json: bool) -> int:
    settings = get_settings()
    settings.ensure_directories()
    log_file = configure_logging(settings.logs_dir, settings.log_level, console=not as_json)
    logger = logging.getLogger("quantresearch.doctor")

    with Timer("environment doctor", logger=logger):
        checks = {
            "version": __version__,
            "python": platform.python_version(),
            "project_root": str(settings.project_root),
            "project_root_exists": settings.project_root.is_dir(),
            "raw_data_dir": str(settings.raw_data_dir),
            "raw_data_dir_exists": settings.raw_data_dir.is_dir(),
            "log_file": str(log_file),
        }

    if as_json:
        print(json.dumps(checks, indent=2, sort_keys=True))
    else:
        for key, value in checks.items():
            print(f"{key}: {value}")
    return 0 if all((checks["project_root_exists"], checks["raw_data_dir_exists"])) else 1


def _inspect_universe(input_path: Path, index_id: str, as_of: date, as_json: bool) -> int:
    history = load_component_snapshots(input_path, index_id=index_id)
    result = history.as_of(as_of)
    payload = {
        "index_id": result.index_id,
        "as_of": result.as_of.isoformat(),
        "source_snapshot_date": result.source_snapshot_date.isoformat(),
        "carried_forward": result.carried_forward,
        "member_count": len(result.symbols),
        "members": sorted(result.symbols),
        "snapshot_count": len(history.snapshots),
        "interval_count": len(history.intervals()),
        "acquisition_union_count": len(history.acquisition_union()),
        "source_path": str(history.source_path),
        "source_sha256": history.source_sha256,
    }
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        for key, value in payload.items():
            if key != "members":
                print(f"{key}: {value}")
        print("members:")
        print("\n".join(payload["members"]))
    return 0


def _research_database(command: str, database: Path | None, as_json: bool) -> int:
    path = database or get_settings().research_db_path
    store = ResearchStore(path)
    if command == "init":
        store.initialize()
    payload = store.inspect()
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"database_path: {payload['database_path']}")
        print(f"schema_version: {payload['schema_version']}")
        for table, count in payload["row_counts"].items():
            print(f"{table}: {count}")
    return 0


def _walk_forward_schedule(
    start_year: int, last_completed_year: int, warmup_days: int, as_json: bool
) -> int:
    windows = generate_walk_forward_windows(
        start_year, last_completed_year, warmup_days=warmup_days
    )
    payload = {
        "start_year": start_year,
        "last_completed_year": last_completed_year,
        "window_count": len(windows),
        "windows": [window.to_dict() for window in windows],
    }
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"window_count: {len(windows)}")
        for window in windows:
            print(
                f"{window.window_id} train={window.train_start}..{window.train_end} "
                f"forward={window.forward_start}..{window.forward_end} "
                f"state={window.forward_state.value}"
            )
    return 0


def _validate_reviews(mappings: Path | None, exclusions: Path | None, as_json: bool) -> int:
    if mappings is None and exclusions is None:
        raise ValueError("At least one review decision file is required")
    payload: dict[str, object] = {}
    readiness: list[bool] = []
    if mappings is not None:
        imported_mappings = load_mapping_decisions(mappings)
        readiness.append(imported_mappings.ready)
        payload["mappings"] = {
            "source_path": str(imported_mappings.source_path),
            "source_sha256": imported_mappings.source_sha256,
            "records": len(imported_mappings.registry.mappings),
            "approved": imported_mappings.counts.get("approved", 0),
            "pending": imported_mappings.counts.get("pending", 0),
            "rejected": imported_mappings.counts.get("rejected", 0),
        }
    if exclusions is not None:
        imported_exclusions = load_exclusion_decisions(exclusions)
        readiness.append(imported_exclusions.ready)
        payload["exclusions"] = {
            "source_path": str(imported_exclusions.source_path),
            "source_sha256": imported_exclusions.source_sha256,
            "records": len(imported_exclusions.registry.exclusions),
            "approved": imported_exclusions.counts.get("approved", 0),
            "pending": imported_exclusions.counts.get("pending", 0),
            "rejected": imported_exclusions.counts.get("rejected", 0),
        }
    payload["ready"] = all(readiness)
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"ready: {payload['ready']}")
        for category in ("mappings", "exclusions"):
            if category in payload:
                for key, value in payload[category].items():
                    print(f"{category}_{key}: {value}")
    return 0 if payload["ready"] else 2


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "doctor":
        return _doctor(args.json)
    if args.command == "universe" and args.universe_command == "inspect":
        return _inspect_universe(args.input, args.index_id, args.as_of, args.json)
    if args.command == "research-db":
        return _research_database(args.research_command, args.database, args.json)
    if args.command == "walk-forward" and args.walk_command == "schedule":
        return _walk_forward_schedule(
            args.start_year,
            args.last_completed_year,
            args.warmup_days,
            args.json,
        )
    if args.command == "review" and args.review_command == "validate":
        return _validate_reviews(args.mappings, args.exclusions, args.json)
    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
