import argparse
import hashlib
import json
import pathlib
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
PARENT = ROOT.parent
DIRECTORIES = {"data", "docs", "lib", "web", "scripts", "tests", "dist", "models", "evidence", "licenses"}
ROOT_FILES = {"package.json", "package-lock.json", "server.mjs", ".npmrc", ".env.example", ".gitignore", "README.md", "THIRD_PARTY.md", "TECHNICAL_NOTE.md", "PERFORMANCE_REPORT.md", "model-manifest.json"}
FORBIDDEN = {".env", "connection.json", "node_modules", ".git", "__pycache__", "private"}

def digest(data):
    return hashlib.sha256(data).hexdigest()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--secret-file", type=pathlib.Path)
    args = parser.parse_args()
    secrets = []
    if args.secret_file:
        config = json.loads(args.secret_file.read_text(encoding="utf-8-sig"))
        for key in ["password", "token", "api_key"]:
            value = config.get(key)
            if isinstance(value, str) and value:
                secrets.append(value.encode("utf-8"))
    required = ["TECHNICAL_NOTE.md", "PERFORMANCE_REPORT.md", "model-manifest.json", "evidence/browser-results.json", "evidence/summary.json", "evidence/persistence.json", "evidence/refresh-results.json", "licenses/model-Apache-2.0.txt", "licenses/onnxruntime-MIT.txt", "dist/index.html"]
    for name in required:
        if not (ROOT / name).is_file():
            raise RuntimeError(f"Missing required deliverable: {name}")
    results = json.loads((ROOT / "evidence/browser-results.json").read_text(encoding="utf-8"))
    if not results.get("success") or not all(results.get("checks", {}).values()):
        raise RuntimeError("Browser verification is not complete")
    files = [(PARENT / "00_队友先读.md", "00_队友先读.md")]
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if any(part in FORBIDDEN for part in relative.parts) or path.suffix in {".pyc", ".db", ".sqlite"}:
            continue
        if (len(relative.parts) == 1 and path.name in ROOT_FILES) or relative.parts[0] in DIRECTORIES:
            files.append((path, "stepfun/" + relative.as_posix()))
    manifest = []
    archive = PARENT / "OB_StepFun_队友提交包_20261028.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as output:
        for path, name in files:
            content = path.read_bytes()
            if any(secret in content for secret in secrets):
                raise RuntimeError(f"Secret scan failed in {name}; no secret value was printed")
            manifest.append(f"{digest(content)}  {name}")
            output.writestr(name, content)
        output.writestr("SHA256SUMS.txt", "\n".join(manifest) + "\n")
    with zipfile.ZipFile(archive) as saved:
        if saved.testzip() is not None:
            raise RuntimeError("ZIP CRC verification failed")
        for line in saved.read("SHA256SUMS.txt").decode("utf-8").splitlines():
            expected, name = line.split("  ", 1)
            if digest(saved.read(name)) != expected:
                raise RuntimeError(f"Archive digest mismatch: {name}")
        for name in saved.namelist():
            parts = pathlib.PurePosixPath(name).parts
            if ".." in parts or any(part in FORBIDDEN for part in parts):
                raise RuntimeError(f"Unsafe archive entry: {name}")
    print(json.dumps({"archive": str(archive), "bytes": archive.stat().st_size, "sha256": digest(archive.read_bytes()), "files": len(files) + 1, "secret_patterns_checked": len(secrets), "crc_and_all_entry_sha256": "PASS"}, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
