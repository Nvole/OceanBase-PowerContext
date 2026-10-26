# Dify：离谱辩题

夜班辩论俱乐部。玩家丢出一句离谱辩词，杠精主持人翻出 seekdb 里的旧档案来抬杠，再把这一轮记回去。

Dify DSL 编排「输入 → HTTP 检索 → 回应 → HTTP 保存 → 输出」，文件是 [docs/absurd_debate.dsl.yml](docs/absurd_debate.dsl.yml)。本机没有 Dify 界面，DSL 没有导入。可玩入口是 `127.0.0.1:18604`，一局结果在 [results/sample_run.json](results/sample_run.json)。

运行、样例和限制见 [docs/运行说明.md](docs/运行说明.md)。

数据库账号是 `track04_dify`，连接信息在本目录权限 600 的 `.env`。不要覆盖，也不要打印密码。不要重启 `127.0.0.1:2881`。

在 `~/oceanbase` 执行 `. ./env.sh` 后，用 `uv run --locked` 启动 `src/server.py`。collection 名是 `track04_debate`。