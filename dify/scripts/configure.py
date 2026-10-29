import argparse
import json
import re
import secrets
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description="Create local configuration without printing secrets")
    parser.add_argument("--connection-file", type=Path)
    parser.add_argument("--database", default="dify_v2_debate")
    arguments = parser.parse_args()
    destination = PROJECT / ".env"
    if destination.exists():
        raise SystemExit(".env already exists; edit it locally instead of overwriting it")
    if not re.fullmatch(r"dify_[a-z0-9_]{1,48}", arguments.database):
        parser.error("database must be named dify_<lowercase_letters_or_digits>")
    settings = {}
    for line in (PROJECT / ".env.example").read_text(encoding="utf-8").splitlines():
        name, value = line.split("=", 1)
        settings[name] = value
    settings["SEEKDB_DATABASE"] = arguments.database
    for name in ("DIFY_SECRET_KEY", "DIFY_DB_PASSWORD", "DIFY_REDIS_PASSWORD", "DIFY_SANDBOX_KEY"):
        settings[name] = secrets.token_hex(24)
    if arguments.connection_file:
        private = json.loads(arguments.connection_file.read_text(encoding="utf-8-sig"))
        for name in ("user", "password", "port"):
            settings["SEEKDB_" + name.upper()] = str(private[name])
    if any("\n" in value or "\r" in value or "$" in value or "'" in value for value in settings.values()):
        raise SystemExit("Use environment injection for credentials containing quotes, dollar signs or line breaks")
    with destination.open("x", encoding="utf-8", newline="\n") as output:
        output.write("".join(f"{name}='{value}'\n" for name, value in settings.items()))
    destination.chmod(0o600)
    print("Created private .env; set SEEKDB_HOST/USER/PASSWORD for your machine. No credentials printed.")


if __name__ == "__main__":
    main()
