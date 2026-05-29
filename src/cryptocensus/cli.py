"""Command-line interface.

The same entry point runs every role so one image serves the whole fleet:

    cryptocensus seed   --file refs.txt          # coordinator: fill the queue
    cryptocensus work   [--idle-exit N]          # worker: process images (any machine)
    cryptocensus analyze --dataset <output_dir>  # aggregate into the census results
    cryptocensus stats                           # queue introspection
    cryptocensus requeue-stale                   # recover a crashed worker's tasks

Workers write their per-image bundles to CC_OUTPUT_DIR. On a multi-machine run, merge
the hosts' output directories (a plain copy; filenames are content/digest addressed and
deduplicate on merge) and point `analyze` at the merged directory.
"""

from __future__ import annotations

import argparse
import logging
import sys

from . import __version__
from .analyze import analyze, format_report
from .config import settings
from .coordinator import seed
from .queue import TaskQueue
from .sampling import from_file
from .worker import run_worker


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cryptocensus", description=__doc__)
    parser.add_argument("--version", action="version", version=f"cryptocensus {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_seed = sub.add_parser("seed", help="enqueue image references")
    p_seed.add_argument("--file", help="file with one image reference per line")
    p_seed.add_argument("refs", nargs="*", help="image references given inline")

    p_work = sub.add_parser("work", help="run a worker loop")
    p_work.add_argument("--idle-exit", type=int, default=0,
                        help="exit after N consecutive empty claims (0 = run forever)")

    p_analyze = sub.add_parser("analyze", help="aggregate an output directory into census results")
    p_analyze.add_argument("--dataset", required=True, help="worker output directory to analyze")

    sub.add_parser("stats", help="print queue statistics")
    sub.add_parser("requeue-stale", help="return in-flight tasks to the pending queue")
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args = _build_parser().parse_args(argv)

    if args.command == "seed":
        refs = list(args.refs)
        if args.file:
            refs.extend(from_file(args.file))
        if not refs:
            print("no references to seed", file=sys.stderr)
            return 2
        print(f"seeded {seed(refs)} references")
        return 0

    if args.command == "work":
        run_worker(settings, idle_exit=args.idle_exit)
        return 0

    if args.command == "analyze":
        summary = analyze(args.dataset)
        print(format_report(summary))
        return 0

    if args.command == "stats":
        print(TaskQueue(settings).stats())
        return 0

    if args.command == "requeue-stale":
        print(f"recovered {TaskQueue(settings).requeue_stale()} tasks")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
