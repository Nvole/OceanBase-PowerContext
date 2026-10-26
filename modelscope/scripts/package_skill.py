"""Package seekdb-hybrid-lab and check the ModelScope zip limits.

Uses the standard library only. Does not connect to seekdb or read .env.
"""

import json
import subprocess
import sys
import zipfile
from pathlib import Path

TRACK = Path(__file__).resolve().parents[1]
SKILL_MD = TRACK / "src" / "skill" / "seekdb-hybrid-lab" / "SKILL.md"
EXAMPLES = TRACK / "examples"
DIST = TRACK / "dist" / "seekdb-hybrid-lab.zip"
RESULT = TRACK / "results" / "package_check.json"
LIMIT = 5 * 1024 * 1024
REQUIRED_TEXT = (
    "upsert",
    "refresh_index",
    "hybrid_search",
    "query.where_document.$contains",
    "knn.query_embeddings",
    "rank.rrf",
)
FORBIDDEN_EXAMPLE_TOKENS = (
    "pyseekdb",
    "pymysql",
    "socket",
    "urllib",
    "requests",
    ".env",
)


def parse_front_matter(text):
    if not text.startswith("---\n"):
        raise SystemExit("SKILL.md is missing front matter")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise SystemExit("SKILL.md front matter is not closed")
    meta = {}
    for line in text[4:end].splitlines():
        if not line.strip():
            continue
        if ":" not in line:
            raise SystemExit("front matter line has no colon")
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip().strip('"').strip("'")
    return meta, text[end + 5 :]


def has_cjk(text):
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def build_zip():
    DIST.parent.mkdir(parents=True, exist_ok=True)
    if DIST.exists():
        DIST.unlink()
    with zipfile.ZipFile(DIST, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(SKILL_MD, "SKILL.md")
        for path in sorted(EXAMPLES.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(EXAMPLES).as_posix()
            if relative.startswith("../") or relative.startswith("/") or ".." in relative.split("/"):
                raise SystemExit("example path is not safe: " + relative)
            archive.write(path, "examples/" + relative)


def check_zip(skill_text):
    with zipfile.ZipFile(DIST) as archive:
        names = archive.namelist()
        for name in names:
            if name.startswith("/") or ".." in Path(name).parts:
                raise SystemExit("unsafe zip member: " + name)
            if Path(name).name == ".env":
                raise SystemExit("zip must not contain .env")
        skill_members = [name for name in names if Path(name).name == "SKILL.md"]
        if skill_members != ["SKILL.md"]:
            raise SystemExit("zip root must contain exactly one SKILL.md")
        packed = archive.read("SKILL.md").decode("utf-8")
        if packed != skill_text:
            raise SystemExit("zip SKILL.md does not match the source")
        records = json.loads(archive.read("examples/three_records.json").decode("utf-8"))
    if not isinstance(records, list) or len(records) != 3:
        raise SystemExit("example must contain exactly 3 records")
    return names, records


def main():
    skill_text = SKILL_MD.read_text(encoding="utf-8")
    meta, body = parse_front_matter(skill_text)
    if meta.get("name") != "seekdb-hybrid-lab":
        raise SystemExit("name must be seekdb-hybrid-lab")
    if not meta.get("version"):
        raise SystemExit("version is required")
    description = meta.get("description", "")
    if not has_cjk(description):
        raise SystemExit("description must be Chinese")
    missing = [item for item in REQUIRED_TEXT if item not in body]
    if missing:
        raise SystemExit("SKILL.md missing: " + ", ".join(missing))
    example_script = (EXAMPLES / "hybrid_search_calls.py").read_text(encoding="utf-8")
    forbidden = [token for token in FORBIDDEN_EXAMPLE_TOKENS if token in example_script]
    if forbidden:
        raise SystemExit("example script is not database-free: " + ", ".join(forbidden))
    completed = subprocess.run(
        [sys.executable, str(EXAMPLES / "hybrid_search_calls.py")],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        raise SystemExit(completed.stderr.strip() or "example script failed")
    payload = json.loads(completed.stdout)
    if len(payload["upsert"]["ids"]) != 3:
        raise SystemExit("example script did not emit 3 upsert ids")
    build_zip()
    names, records = check_zip(skill_text)
    size = DIST.stat().st_size
    if size >= LIMIT:
        raise SystemExit("zip is not smaller than 5MB")
    result = {
        "passed": True,
        "skill_name": meta["name"],
        "version": meta["version"],
        "description_language": "zh",
        "zip": str(DIST),
        "zip_bytes": size,
        "zip_under_5mb": True,
        "skill_md_at_zip_root": True,
        "skill_md_count": 1,
        "zip_members": names,
        "example_records": len(records),
        "example_ids": [item["id"] for item in records],
        "required_steps": ["upsert", "refresh_index", "hybrid_search"],
        "required_paths": list(REQUIRED_TEXT[3:]),
        "example_ran_without_database": True,
        "seekdb_contacted": False,
    }
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": True, "zip_bytes": size, "example_records": 3}, ensure_ascii=False))


if __name__ == "__main__":
    main()
