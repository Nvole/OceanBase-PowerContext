# 高德：周边去哪儿

本题交付物是 [SKILL.md](SKILL.md)，Skill 名称是 `around-where-to-go`。它指导 Agent 使用评测平台已经配置的高德 MCP：先用 `maps_around_search` 检索附近地点，再用 `maps_direction_walking` 查询步行路线，最多返回 3 家符合条件的地点，并给出步行距离、步行时间和有数据依据的推荐理由。步行时间不能用直线距离代替；不够就少返回；未核实和失败不能编造。

不在 Skill 中填写 API Key，不调用高德 API，不做设备定位。长期记忆、多轮、PowerMem 和 seekdb 不是本题要求，本目录不使用、也不修改 seekdb。

## 本地检查

```powershell
python tests/check_skill.py
```

脚本只读取 `SKILL.md` 和 `results/checklist.json`，确认工具名、步行路线、最多 3 家、未核实、失败处理和禁止直线距离都已写明，并刷新 `results/verification.json`。

## 目录

| 路径 | 用途 |
| --- | --- |
| `SKILL.md` | 参赛 Skill |
| `docs/oss_survey.md` | 官方工具名与开源实现差异，仅作核对记录 |
| `docs/task.md` | 早期课程笔记，不是本题提交物 |
| `tests/check_skill.py` | 本地文案检查 |
| `results/checklist.json` | 题面第三节四个场景和第四节三条的完成记录 |
| `results/verification.json` | 最近一次检查结果 |

连接信息如果出现在本目录 `.env` 中，只属于既有环境，不要覆盖，也不要写入 Skill。
