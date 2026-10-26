# seekdb-hybrid-lab 打包与上传

Skill 名称是 `seekdb-hybrid-lab`。`SKILL.md` 的 `description` 使用中文，正文按顺序说明 `upsert`、`refresh_index` 和 `hybrid_search`。混合检索的三个参数位置是 `query.where_document.$contains`、`knn.query_embeddings` 和 `rank.rrf`。示例固定为 3 条，见 `examples/three_records.json`。

打包要求来自魔搭 OpenAPI 对 `skill_file` 的说明：

- zip 根目录恰好有一个 `SKILL.md`。
- 可以包含 `examples/` 等子目录。
- front matter 包含 `name`、`version`、`description`。
- zip 小于 5MB。

在 A6000 上用远程 Python 3 打包并检查：

```bash
python3 scripts/package_skill.py
python3 scripts/upload_skill.py
```

`package_skill.py` 把 `src/skill/seekdb-hybrid-lab/SKILL.md` 和 `examples/` 打进 `dist/seekdb-hybrid-lab.zip`，并写入 `results/package_check.json`。示例脚本只打印调用参数，不连接 seekdb，不读取 `.env`。

`upload_skill.py` 只从环境变量 `MODELSCOPE_API_TOKEN` 读取令牌。变量不存在时不访问网络，把 `results/upload_result.json` 的 `uploaded` 写为 false。令牌不会写入文件、日志或命令输出。脚本不修改 `.env`。

有令牌时，脚本按魔搭 OpenAPI 上传 zip 并创建私有 Skill。公开发布需要另行确认，不要在未确认时改成公开。上传成功后，提交给测试平台的应是 Skill 页面网址或编号，而不是账号主页或 Skill 名称。
