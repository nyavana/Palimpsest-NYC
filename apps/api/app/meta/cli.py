"""Manual CLI for appending SessionRecord entries.

Usage:
    python -m app.meta.cli append \\
        --goal "scaffold fastapi backend" \\
        --prompt-tokens 12034 --completion-tokens 8501 \\
        --cost-usd 0.21 --outcome success

    python -m app.meta.cli summarize
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone

from app.meta.session_log import SessionLogger, SessionRecord, build_default_logger


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def cmd_append(args: argparse.Namespace, logger: SessionLogger) -> int:
    started = args.started_at or _now_iso()
    session_id = args.session_id or f"{started}-{uuid.uuid4().hex[:6]}"
    record = SessionRecord(
        session_id=session_id,
        started_at=started,
        ended_at=args.ended_at or _now_iso(),
        goal=args.goal,
        model=args.model,
        prompt_tokens=args.prompt_tokens,
        completion_tokens=args.completion_tokens,
        cost_usd=args.cost_usd,
        files_touched=args.files or [],
        human_edits_after=args.human_edits,
        lines_added=args.lines_added,
        lines_removed=args.lines_removed,
        outcome=args.outcome,
        notes=args.notes or "",
        tags=dict(pair.split("=", 1) for pair in (args.tags or [])),
    )
    path = logger.append(record)
    print(f"appended session={record.session_id} → {path}")
    return 0


def cmd_summarize(_: argparse.Namespace, logger: SessionLogger) -> int:
    summary = logger.summarize()
    print(json.dumps(summary, indent=2))
    return 0


def cmd_seed(_: argparse.Namespace, logger: SessionLogger) -> int:
    logger.seed_first_record()
    print("first-record seed complete")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="app.meta.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_append = sub.add_parser("append", help="Append a SessionRecord")
    p_append.add_argument("--session-id")
    p_append.add_argument("--started-at")
    p_append.add_argument("--ended-at")
    p_append.add_argument("--goal", required=True)
    p_append.add_argument("--model", default="claude-opus-4-6[1m]")
    p_append.add_argument("--prompt-tokens", type=int, default=0)
    p_append.add_argument("--completion-tokens", type=int, default=0)
    p_append.add_argument("--cost-usd", type=float, default=0.0)
    p_append.add_argument("--files", nargs="*", default=[])
    p_append.add_argument("--human-edits", type=int, default=0)
    p_append.add_argument("--lines-added", type=int, default=0)
    p_append.add_argument("--lines-removed", type=int, default=0)
    p_append.add_argument(
        "--outcome",
        choices=["success", "partial", "failure", "interrupted"],
        default="success",
    )
    p_append.add_argument("--notes")
    p_append.add_argument("--tags", nargs="*", help="key=value pairs")
    p_append.set_defaults(handler=cmd_append)

    p_sum = sub.add_parser("summarize", help="Aggregate all recorded sessions")
    p_sum.set_defaults(handler=cmd_summarize)

    p_seed = sub.add_parser("seed", help="Write the first scaffold record")
    p_seed.set_defaults(handler=cmd_seed)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logger = build_default_logger()
    return int(args.handler(args, logger))


if __name__ == "__main__":
    sys.exit(main())
