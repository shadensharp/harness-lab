from __future__ import annotations

import argparse

from repo_harness_lab.cli.commands import evals, info, run, runs



def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="repo-harness-lab")
    subparsers = parser.add_subparsers(dest="command", required=True)

    info.register(subparsers)
    run.register(subparsers)
    runs.register(subparsers)
    evals.register(subparsers)
    return parser



def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.error(f"unknown command: {args.command}")
        return 2
    return int(handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
