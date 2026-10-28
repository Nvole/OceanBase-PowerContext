"""Generate the Dify 1.9.x (DSL 0.3.1) variant of the wishwell DSL for local
demos. The submission DSL stays 0.5.0 (Dify 1.12+); this variant only strips
0.5-only fields so the same graph can be imported in Dify 1.9.x.

Usage: python scripts/build_local_variant.py
"""
from pathlib import Path

TRACK = Path(__file__).resolve().parents[1]
SRC = TRACK / "docs" / "wishwell.dsl.yml"
DST = TRACK / "docs" / "wishwell-dify-1.9.x.yml"

DROP_LINES = {
    "prompt_config:",
    "jinja2_variables: []",
    "reasoning_format: tagged",
    "structured_output: null",
    "structured_output_enabled: false",
}


def convert(text):
    text = text.replace('version: "0.5.0"', 'version: "0.3.1"')
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped in DROP_LINES:
            continue
        lines.append(line)
    return "\n".join(lines) + "\n"


def main():
    raw = SRC.read_text(encoding="utf-8")
    DST.write_text(convert(raw), encoding="utf-8")
    print(f"written {DST}")


if __name__ == "__main__":
    main()