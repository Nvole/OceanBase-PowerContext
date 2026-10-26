# 验证样例

在项目根目录执行，不要打印 `.env`。

```sh
cd /data/zouyuanwei/oceanbase
. ./env.sh
uv run --locked python tracks/05_qoder_database_tools/tests/test_labnotes.py
```

## 样例一：已有中文材料

- 初始数据：`src/seed_labnotes.json` 中的 12 条中文笔记，写入集合 `track05_labnotes`。
- 输入：关键词 `青屿纪要`，语义查询「组会里怎样把全文和向量结果融合」。
- 操作：测试调用 `hybrid_search`，条件是 `where_document.$contains`、knn 和 `rank.rrf`。写入种子后已经 `refresh_index`。
- 预期：命中种子 `ln-seed-02` / 代号 `LNSEED02`，原文同时含有「青屿纪要」。其他种子不含这四个字。

## 样例二：新导入的独特代号

- 初始数据：样例一已经写入。
- 输入：标题「临时核对材料」，正文是一条新的中文组会笔记。代号由程序生成，形如 `LN` 加 10 位十六进制，不与种子重复。
- 操作：`upsert` 后调用 `refresh_index`，立刻用该代号做关键词和语义查询。
- 预期：混合检索的 `hybrid_ids` 和过滤后的命中都包含这条新材料，原文中能看到该代号。

## 样例三：服务绑定

- 操作：启动测试里的 HTTP 服务，请求 `/api/health`、`/api/search` 和 `/api/import`。
- 预期：监听地址是 `127.0.0.1:18605`。健康检查里的 `qoder_sites` 为 `blocked`。接口导入的新代号也能检索到。响应和 `docs/last_run.json` 都不含数据库口令。

手动打开页面时，另开转发 `ssh -N -L 18605:127.0.0.1:18605 A6000-zyw`，浏览器访问 `http://127.0.0.1:18605`。不要把服务改绑到其他地址。

通过后，机器上的摘要在 `results/hybrid_search.json`，可提交副本在 `docs/last_run.json`。
