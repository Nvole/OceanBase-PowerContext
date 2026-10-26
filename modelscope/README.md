# 魔搭：领域智能体与开源交付

本题当前交付的是自写 Skill `seekdb-hybrid-lab`。它用中文说明一次最小混合检索实验：先 `upsert` 写入三条示例，再 `refresh_index`，然后调用 `hybrid_search`。全文条件是 `query.where_document.$contains`，向量条件是 `knn.query_embeddings`，融合排序是 `rank.rrf`。

| 路径 | 内容 |
| --- | --- |
| `src/skill/seekdb-hybrid-lab/SKILL.md` | Skill 正文 |
| `examples/three_records.json` | 3 条示例数据 |
| `examples/hybrid_search_calls.py` | 只组装调用参数，不连接数据库 |
| `dist/seekdb-hybrid-lab.zip` | 魔搭上传包，根目录只有一个 `SKILL.md` |
| `scripts/package_skill.py` | 远程 `python3` 打包并检查 |
| `scripts/upload_skill.py` | 没有 `MODELSCOPE_API_TOKEN` 时不上传 |
| `docs/task.md` | 题意索引 |
| `docs/modelscope_upload.md` | 打包和上传说明 |
| `results/package_check.json` | 打包检查结果 |
| `results/upload_result.json` | 上传结果，未配置令牌时 `uploaded` 为 false |

题意、范围和建议仍见 [docs/task.md](docs/task.md)。数据库账号信息只放在权限为 600 的 `.env` 中。不要把 `.env` 或令牌写入 Skill、日志和仓库。示例脚本不连接 seekdb。

在服务器项目目录执行：

```bash
python3 scripts/package_skill.py
python3 scripts/upload_skill.py
```
