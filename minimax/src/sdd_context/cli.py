"""CLI entry. build reads query hits; it does not open material files by name."""

import argparse
import json
import sys

from sdd_context.assemble import assemble, extract_terms
from sdd_context.store import import_materials, search
from sdd_context.task_state import read_state, save_marker


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="sdd_context")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("import")
    build = commands.add_parser("build")
    build.add_argument("--task", required=True)
    build.add_argument("--out")
    commands.add_parser("show-state")
    save = commands.add_parser("save-state")
    save.add_argument("--text", required=True)
    args = parser.parse_args(argv)
    if args.command == "import":
        payload = import_materials()
    elif args.command == "build":
        payload = build_context(args.task)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
    elif args.command == "show-state":
        payload = read_state()
    else:
        payload = save_marker(args.text)
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


def build_context(task: str) -> dict:
    terms = extract_terms(task)
    hits, queries = search(terms)
    try:
        state = read_state()
    except Exception as exc:
        state = {"status": "blocked", "reason": type(exc).__name__}
    return assemble(task, terms, hits, state, queries)
