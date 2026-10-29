import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description="Start, import, publish and verify the complete Dify application")
    parser.add_argument("--initialize-local", action="store_true")
    parser.add_argument("--seekdb-host", default="127.0.0.1")
    arguments = parser.parse_args()
    if not (PROJECT / ".env").is_file():
        raise SystemExit("Run python scripts/configure.py and configure the private .env first")
    docker = json.loads(os.environ.get("DIFY_DOCKER_COMMAND", '["docker"]'))

    def run(command):
        result = subprocess.run(command, cwd=PROJECT)
        if result.returncode:
            raise SystemExit(result.returncode)

    run(docker + ["compose", "config", "--quiet"])
    run(docker + ["compose", "build", "debate"])
    run(docker + ["compose", "run", "--rm", "--no-deps", "debate", "python", "src/initialize.py"])
    run(docker + ["compose", "up", "-d"])
    imported = [sys.executable, "scripts/import_dify.py"]
    if arguments.initialize_local:
        imported.append("--initialize-local")
    run(imported)
    run([sys.executable, "scripts/verify_dify.py", "--seekdb-host", arguments.seekdb_host, "--restart-backend"])
    run([sys.executable, "scripts/verify_submission.py", "--local-root", str(PROJECT.parent), "--output", str(PROJECT / ".runtime/local_release_check.json")])
    print("Local Dify application is verified. Push the source, then run the anonymous remote clone checker before platform submission.")


if __name__ == "__main__":
    main()
