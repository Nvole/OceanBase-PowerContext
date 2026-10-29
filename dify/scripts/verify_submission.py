import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit


REQUIRED = (
    "README.md", "requirements.txt", "compose.yaml", "Dockerfile", ".env.example", ".gitignore",
    "src/db.py", "src/server.py", "src/debate.py", "src/respond.py", "src/hashvec.py", "src/initialize.py",
    "scripts/import_dify.py", "scripts/verify_dify.py", "scripts/configure.py", "scripts/dify_client.py",
    "docs/verification_sample.md",
    "docs/absurd_debate.dsl.yml", "data/seed_arguments.json", "evidence/dify_import.json", "evidence/dify_acceptance.json",
)


def audit_checkout(root):
    project = root / "dify"
    missing = ["dify/" + name for name in REQUIRED if not (project / name).is_file()]
    if missing:
        raise ValueError("Missing required tracked files: " + ", ".join(missing))
    unsafe = [path.relative_to(root).as_posix() for path in project.rglob("*")
              if path.is_file() and (path.name == ".env" or path.name == "connection.json" or ".runtime" in path.parts or ".venv" in path.parts)]
    if unsafe:
        raise ValueError("Private files must not be committed: " + ", ".join(unsafe[:20]))
    imported = json.loads((project / "evidence/dify_import.json").read_text(encoding="utf-8"))
    acceptance = json.loads((project / "evidence/dify_acceptance.json").read_text(encoding="utf-8"))
    if imported.get("published") is not True or not imported.get("exported_from_real_dify"):
        raise ValueError("No actual Dify import/publication evidence")
    if imported.get("dsl_sha256") != hashlib.sha256((project / "docs/absurd_debate.dsl.yml").read_bytes()).hexdigest():
        raise ValueError("DSL changed after Dify import; import and verify again")
    required_checks = ["dify_rejects_invalid_app_token", "new_memory_reused_by_next_dify_run",
                       "retry_does_not_duplicate_cards", "quotes_and_newlines_survive_dify",
                       "four_dify_generated_cards_exist_in_real_database", "backend_restart_preserves_seekdb_memory"]
    if acceptance.get("passed") is not True or not all(acceptance.get("checks", {}).get(name) is True for name in required_checks):
        raise ValueError("Actual Dify/seekdb/restart acceptance has not passed")
    runs = acceptance.get("workflow_runs", [])
    if len(runs) < 4 or any(run.get("status") != "succeeded" or run.get("total_steps", 0) < 7 or not re.fullmatch(r"[0-9a-f-]{36}", run.get("run_id", "")) for run in runs):
        raise ValueError("Incomplete actual Dify workflow-run records")
    for run in runs:
        if acceptance.get("checks", {}).get(run["name"] + "_node_execution_trace") is not True:
            raise ValueError("Missing actual Dify node execution trace for " + run["name"])
    fingerprints = acceptance.get("source_sha256", {})
    if not fingerprints:
        raise ValueError("Missing source fingerprint")
    for name, expected in fingerprints.items():
        path = (project / name).resolve()
        if not path.is_relative_to(project.resolve()) or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("Source differs from the tested release: " + name)
    return {"required_files": len(REQUIRED), "tested_source_files": len(fingerprints), "dify_runs": len(runs), "acceptance_passed": True}


def main():
    parser = argparse.ArgumentParser(description="Anonymous fresh clone and exact remote SHA verification")
    parser.add_argument("--repository")
    parser.add_argument("--branch", default="2026-competition-ecosystem")
    parser.add_argument("--commit")
    parser.add_argument("--local-root", type=Path)
    parser.add_argument("--output", type=Path, default=Path.cwd() / "dify_submission_check.json")
    arguments = parser.parse_args()
    report = {"checked_at": datetime.now(timezone.utc).isoformat(), "passed": False, "anonymous_remote_clone": False}
    try:
        if arguments.local_root:
            if arguments.repository or arguments.commit:
                raise ValueError("Use either local audit or remote clone verification")
            report["audit"] = audit_checkout(arguments.local_root.resolve())
            report["mode"] = "local_content_only_not_remote_checkout"
            report["passed"] = True
        else:
            if not shutil.which("git"):
                raise ValueError("Install Git, or run this script inside Linux/WSL with Git")
            if not arguments.repository or not arguments.commit:
                raise ValueError("Both --repository and the full --commit SHA are required")
            parsed = urlsplit(arguments.repository)
            if parsed.scheme != "https" or parsed.hostname != "github.com" or parsed.username or parsed.password or parsed.query or parsed.fragment or not re.fullmatch(r"/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?", parsed.path):
                raise ValueError("Use https://github.com/OWNER/REPOSITORY.git without credentials, /tree/, /commit/, query or fragment")
            if arguments.branch != "2026-competition-ecosystem":
                raise ValueError("This release targets the 2026-competition-ecosystem branch")
            if not re.fullmatch(r"[0-9a-fA-F]{40}", arguments.commit):
                raise ValueError("--commit must be the complete 40-character remote Git commit SHA")
            environment = os.environ.copy()
            environment.update({"GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_ASKPASS": ""})

            def git(*parameters, cwd=None):
                result = subprocess.run(["git", "-c", "credential.helper=", "-c", "core.askPass=", *parameters], cwd=cwd,
                                        env=environment, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
                if result.returncode:
                    raise ValueError("Git " + parameters[0] + " failed: " + result.stderr[-1000:])
                return result.stdout.strip()

            with tempfile.TemporaryDirectory(prefix="dify_remote_checkout_") as directory:
                checkout = Path(directory) / "checkout"
                git("clone", "--no-checkout", "--single-branch", "--branch", arguments.branch, "--", arguments.repository, str(checkout))
                remote_head = git("rev-parse", "refs/remotes/origin/" + arguments.branch, cwd=checkout)
                if remote_head.lower() != arguments.commit.lower():
                    raise ValueError("SHA does not match the pushed branch HEAD. Remote HEAD is " + remote_head)
                git("checkout", "--detach", arguments.commit, cwd=checkout)
                modes = git("ls-tree", "-r", "HEAD", "dify", cwd=checkout)
                if any(line.startswith(("120000 ", "160000 ")) for line in modes.splitlines()):
                    raise ValueError("Do not use symbolic links/submodules for required Dify files")
                report["audit"] = audit_checkout(checkout)
                report.update({"repository": arguments.repository, "branch": arguments.branch,
                               "commit": remote_head, "anonymous_remote_clone": True, "passed": True})
    except Exception as error:
        report["error"] = str(error)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if report.get("passed") and report.get("anonymous_remote_clone"):
        form = arguments.output.with_suffix(".submission.txt")
        form.write_text("Dify 800513\nRepository: " + report["repository"] + "\nBranch: " + report["branch"] + "\nCommit: " + report["commit"] + "\nDirectory: dify/\nEntry: Follow dify/README.md; real Dify Workflow and seekdb evidence in dify/evidence/\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
