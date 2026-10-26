"""Record failing date-range tests, then the passing revision and acceptance."""

import hashlib
import os
import subprocess
import sys
from pathlib import Path

TRACK = Path(__file__).resolve().parents[1]
PROJECT = TRACK.parents[1]
TESTS = "tracks/07_minimax_engineering_context/tests"
COMMAND = (
    "cd /data/zouyuanwei/oceanbase && . ./env.sh && "
    "PYTHONPATH=tracks/07_minimax_engineering_context/src "
    "uv run --locked python -m unittest discover -s "
    "tracks/07_minimax_engineering_context/tests -v"
)
DATE_FAILS = (
    "test_filter_by_date_range",
    "test_filter_date_start_only",
    "test_filter_date_end_only",
    "test_filter_date_single_day_inclusive",
    "test_filter_date_accepts_date_objects",
    "test_filter_date_inverted_range_is_empty",
    "test_filter_date_uses_calendar_day",
    "test_filter_date_with_amount_and_status",
)
ALWAYS_OK = (
    "test_filter_by_min_amount",
    "test_filter_by_max_amount",
    "test_filter_min_amount_is_inclusive",
    "test_filter_by_status",
    "test_filter_status_is_case_sensitive",
    "test_filter_amount_and_status",
    "test_filter_without_constraints_preserves_order",
    "test_filter_does_not_mutate_input",
    "test_omitted_dates_do_not_filter",
    "test_terms_keep_full_tokens",
    "test_sources_come_from_hit_metadata",
    "test_changed_hit_text_replaces_the_sentence",
    "test_retrieval_modules_do_not_name_materials",
)


def main() -> int:
    _normalize(TRACK)
    live = TRACK / "src" / "lab" / "invoice_filter.py"
    before = TRACK / "results" / "invoice_filter.before.py"
    after_text = live.read_text(encoding="utf-8")
    if 'REVISION = "date-range-applied"' not in after_text:
        print("live module is not the date-range revision", file=sys.stderr)
        return 1
    try:
        live.write_text(before.read_text(encoding="utf-8"), encoding="utf-8")
        before_code = _run_tests(TRACK / "results" / "tests_before.txt", "amount-status-only", live)
        before_log = (TRACK / "results" / "tests_before.txt").read_text(encoding="utf-8")
        if before_code == 0 or not _results(before_log, DATE_FAILS, "FAIL") or not _results(before_log, ALWAYS_OK, "ok"):
            print("before-tests did not fail only on unimplemented date behavior", file=sys.stderr)
            return 1
        if "ERROR:" in before_log:
            print("before-tests contained an error", file=sys.stderr)
            return 1
    finally:
        live.write_text(after_text, encoding="utf-8")
    after_code = _run_tests(TRACK / "results" / "tests_after.txt", "date-range-applied", live)
    after_log = (TRACK / "results" / "tests_after.txt").read_text(encoding="utf-8")
    if after_code != 0 or not _results(after_log, DATE_FAILS + ALWAYS_OK, "ok"):
        print("after-tests did not pass", file=sys.stderr)
        return 1
    _write_diff(before, after_text)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(TRACK / "src")
    completed = subprocess.run(
        [sys.executable, "-m", "sdd_context.acceptance"],
        cwd=str(PROJECT),
        env=env,
        check=False,
    )
    return completed.returncode


def _run_tests(destination: Path, revision: str, code_path: Path) -> int:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(TRACK / "src")
    command = ["uv", "run", "--locked", "python", "-m", "unittest", "discover", "-s", TESTS, "-v"]
    completed = subprocess.run(command, cwd=str(PROJECT), env=env, text=True, capture_output=True)
    digest = hashlib.sha256(code_path.read_bytes()).hexdigest()
    text = "\n".join([
        f"command: {COMMAND}",
        "code_file: src/lab/invoice_filter.py",
        f"code_sha256: {digest}",
        f"revision: {revision}",
        "",
        completed.stdout,
        completed.stderr,
        f"exit_code: {completed.returncode}",
        "",
    ])
    destination.write_text(text, encoding="utf-8")
    return completed.returncode


def _results(log: str, names: tuple[str, ...], expected: str) -> bool:
    for name in names:
        matched = False
        for line in log.splitlines():
            if line.startswith(name + " "):
                matched = line.rstrip().endswith(" ... " + expected) or f" ... {expected}" in line
                if expected == "FAIL":
                    matched = "FAIL" in line
                elif expected == "ok":
                    matched = line.rstrip().endswith(" ... ok")
                break
        if not matched:
            return False
    return True


def _write_diff(before: Path, after_text: str) -> None:
    import difflib
    before_text = before.read_text(encoding="utf-8")
    (TRACK / "results" / "invoice_filter.after.py").write_text(after_text, encoding="utf-8")
    diff = difflib.unified_diff(
        before_text.splitlines(True),
        after_text.splitlines(True),
        fromfile="results/invoice_filter.before.py",
        tofile="src/lab/invoice_filter.py",
    )
    (TRACK / "results" / "invoice_filter.diff").write_text("".join(diff), encoding="utf-8")


def _normalize(root: Path) -> None:
    for path in root.rglob("*"):
        if ".powercontext" in path.parts or not path.is_file():
            continue
        if path.suffix.lower() not in {".py", ".md", ".json", ".txt"}:
            continue
        data = path.read_bytes()
        if b"\r\n" in data:
            path.write_bytes(data.replace(b"\r\n", b"\n"))


if __name__ == "__main__":
    raise SystemExit(main())
