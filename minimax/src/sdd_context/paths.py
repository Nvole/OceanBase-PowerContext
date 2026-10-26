"""Locate the track and the shared project scripts without naming materials."""

from pathlib import Path


def track_root() -> Path:
    return Path(__file__).resolve().parents[2]


def project_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "scripts" / "db.py").is_file():
            return parent
    raise RuntimeError("scripts/db.py was not found")


def env_file() -> Path:
    return track_root() / ".env"
