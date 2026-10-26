# -*- coding: utf-8 -*-
"""Check SKILL.md for the Amap nearby-place rules. Does not call Amap."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL_PATH = ROOT / "SKILL.md"
CHECKLIST_PATH = ROOT / "results" / "checklist.json"
VERIFICATION_PATH = ROOT / "results" / "verification.json"

REQUIRED_CHECKS = [
    (
        "tool_names",
        "工具名",
        ["maps_around_search", "maps_text_search", "maps_search_detail", "maps_direction_walking"],
    ),
    ("walking_route", "步行路线", ["maps_direction_walking", "步行路线"]),
    ("max_3", "最多 3 家", ["最多返回 3"]),
    ("unverified", "未核实", ["未核实"]),
    ("failure_handling", "失败处理", ["查询失败", "没有结果", "不编造"]),
    ("no_straight_line", "禁止直线距离", ["禁止用直线距离代替"]),
]


def load_text(path):
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def check_phrases(text, phrases):
    missing = [phrase for phrase in phrases if phrase not in text]
    return missing


def check_checklist(payload):
    expected = [
        "名称、用途和适用场景",
        "查询地点、获取步行路线、筛选推荐",
        "回答格式",
        "普通推荐",
        "时间限制",
        "偏好排序",
        "结果不足或查询异常",
    ]
    errors = []
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list) or len(items) < 7:
        return ["checklist items missing"]
    blob = json.dumps(payload, ensure_ascii=False)
    for phrase in expected:
        if phrase not in blob:
            errors.append("missing checklist phrase: " + phrase)
    for item in items:
        if item.get("status") != "done":
            errors.append("item not done: " + str(item.get("id")))
    return errors


def main():
    text = load_text(SKILL_PATH)
    results = []
    failed = False
    if not text:
        failed = True
        results.append({"id": "skill_file", "status": "fail", "detail": "SKILL.md missing"})
    for check_id, label, phrases in REQUIRED_CHECKS:
        missing = check_phrases(text, phrases)
        status = "pass" if not missing else "fail"
        if missing:
            failed = True
        results.append(
            {
                "id": check_id,
                "label": label,
                "status": status,
                "missing": missing,
            }
        )

    checklist_errors = ["results/checklist.json missing"]
    if CHECKLIST_PATH.is_file():
        try:
            checklist_errors = check_checklist(json.loads(CHECKLIST_PATH.read_text(encoding="utf-8")))
        except json.JSONDecodeError as exc:
            checklist_errors = ["checklist json invalid: " + str(exc)]
    if checklist_errors:
        failed = True
    results.append(
        {
            "id": "checklist",
            "label": "题面条目",
            "status": "pass" if not checklist_errors else "fail",
            "missing": checklist_errors,
        }
    )

    report = {
        "track": "03_amap_location_agent",
        "skill": "SKILL.md",
        "amap_api_called": False,
        "passed": not failed,
        "checks": results,
    }
    VERIFICATION_PATH.parent.mkdir(parents=True, exist_ok=True)
    VERIFICATION_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    for item in results:
        missing = item.get("missing") or []
        suffix = "" if not missing else " missing=" + ",".join(missing)
        print(item["status"] + " " + item["id"] + suffix)
    print("passed=" + str(report["passed"]))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
