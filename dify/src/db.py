import json
import os
import re
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]


def load_environment(path=None):
    destination = Path(path or PROJECT / ".env")
    if destination.is_file():
        for line in destination.read_text(encoding="utf-8-sig").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                name, value = stripped.split("=", 1)
                os.environ.setdefault(name.strip(), value.strip().strip("\"'"))


def connection_settings(env_file=None):
    load_environment(env_file)
    private_file = os.environ.get("SEEKDB_CONNECTION_FILE")
    existing = json.loads(Path(private_file).read_text(encoding="utf-8-sig")) if private_file else {}
    settings = {
        "host": os.environ.get("SEEKDB_HOST", existing.get("host", "127.0.0.1")),
        "port": int(os.environ.get("SEEKDB_PORT", existing.get("port", 2881))),
        "user": os.environ.get("SEEKDB_USER", existing.get("user", "")),
        "password": os.environ.get("SEEKDB_PASSWORD", existing.get("password", "")),
        "database": os.environ.get("SEEKDB_DATABASE", "dify_v2_debate"),
    }
    if not settings["user"] or settings["user"].startswith("YOUR_"):
        raise ValueError("Configure SEEKDB_USER before running")
    if not re.fullmatch(r"dify_[a-z0-9_]{1,48}", settings["database"]):
        raise ValueError("Use a dedicated database named dify_<lowercase_letters_or_digits>")
    return settings


def connect_collection_api(env_file=None):
    import pyseekdb

    return pyseekdb.Client(**connection_settings(env_file))


def initialize_database():
    import pymysql

    settings = connection_settings()
    database = settings.pop("database")
    with pymysql.connect(**settings, charset="utf8mb4", autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{database}`")
    return database
