# Dify：离谱辩题

“夜班辩论俱乐部”是一个 Dify Workflow 应用：玩家提交辩手、辩题、立场和辩词，Dify 先调用 HTTP 检索节点从 seekdb 找旧档案，再由代码节点生成主持人反驳，最后调用 HTTP 保存节点把本轮写回 seekdb。

DSL 文件是 [docs/absurd_debate.dsl.yml](docs/absurd_debate.dsl.yml)。导入 Dify 后，应用的主入口是 Dify Workflow UI 或 `/v1/workflows/run` API；`src/server.py` 只是 Dify 调用的 seekdb 工具服务，不是替代 Dify 的用户入口。

## 快速开始

1. 启动 seekdb 工具服务，确保它能被 Dify 访问。原生同机运行可使用 `127.0.0.1:18604`；Dify 在 Docker 中运行时，使用宿主机地址（例如 `http://host.docker.internal:18604`），并让服务绑定 `0.0.0.0`。
2. 在 Dify 1.12+ 中导入 `docs/absurd_debate.dsl.yml`，保留或修改环境变量 `DEBATE_API_BASE` 为上一步的地址。
3. 在 Dify 中发布 Workflow，复制该应用的 API Key。
4. 设置 `DIFY_API_BASE` 和 `DIFY_API_KEY`，运行 `python src/run_dify_api.py`。成功后，脱敏运行证据写入 `results/dify_run.json`。

完整依赖、导入步骤、Docker 连通性和验证样例见 [docs/运行说明.md](docs/运行说明.md)。数据库账号只从本目录权限 600 的 `.env` 读取，不要把密码或 Dify API Key 提交到仓库。

seekdb collection 为 `track04_debate`，负责保存辩词并执行全文加 64 维向量的 `hybrid_search`。Dify 的 HTTP 节点把检索结果和保存动作串进应用主链路。
