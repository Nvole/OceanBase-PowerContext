# MiniMax：工程上下文工具

题意、范围、建议及材料索引见 [docs/task.md](docs/task.md)。

本题数据库和账号均为 `track07_minimax`，连接信息在本目录权限为 600 的 `.env` 中。

目录用途：`src/lab` 是发票筛选，`src/sdd_context` 是工程上下文，`tests/` 放验证，`data/` 放初始发票，`results/` 放测试和检索记录，`docs/` 放规格与运行说明，`minimax/` 放提交材料。

```sh
cd ~/oceanbase
. ./env.sh
uv run --locked python tracks/07_minimax_engineering_context/tests/run_verification.py
```

运行细节、重置方法和已知限制见 [docs/runbook.md](docs/runbook.md)。seekdb 使用 collection `track07_sdd_docs`。PowerContext 只在 `127.0.0.1:18617` 轻量运行。没有 `MINIMAX_API_KEY` 时不编造对话。
