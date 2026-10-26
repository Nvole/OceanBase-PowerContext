# 组会材料检索

组会前要在聊天记录、实验笔记和上周幻灯片里翻材料。这个小服务把中文组会材料放进 seekdb，用全文关键词、向量近邻和 RRF 混合检索找回来。

数据库和账号都是 `track05_qoder`。连接信息在本目录权限为 600 的 `.env` 中。不要覆盖这个文件，不要把口令写进代码、结果或页面。

## 做什么

- 至少 12 条自拟中文材料进入集合 `track05_labnotes`。种子在 `src/seed_labnotes.json`，运行时会复制到 `data/labnotes.json`。
- 检索调用 `hybrid_search`：`where_document.$contains`、显式 `knn` 向量、`rank.rrf`。
- 写入种子或新材料之后调用 `refresh_index`。新导入的独特代号随后可以用同一条混合检索找到。
- 向量是 64 维字符片段哈希，只为把 knn 链路跑通。不下载嵌入模型，也不调用推理接口。
- 服务只监听 `127.0.0.1:18605`。页面、`/api/search` 和 `/api/import` 使用同一套函数。

## Qoder Sites

状态：**blocked**。

当前环境没有可用的 Qoder 个人账号，不能登录 Qoder Sites，也不能把站点可见范围设为「任何人都可访问」。因此没有项目网站网址。这里不编造网址、账号 UID、对话截图或录屏。本机 `127.0.0.1:18605` 只是回环体验入口，不能代替 Qoder Sites。

Qoder 开发记录同样是 **blocked**：没有可核对的 Qoder 会话。

## 运行

在 A6000 上：

```sh
cd /data/zouyuanwei/oceanbase
. ./env.sh
uv run --locked python tracks/05_qoder_database_tools/tests/test_labnotes.py
uv run --locked python tracks/05_qoder_database_tools/src/server.py
```

服务启动时会写入种子并刷新索引，然后只绑定 `127.0.0.1:18605`。从本机查看页面可以另开一条转发，不要改绑定地址：

```powershell
ssh -N -L 18605:127.0.0.1:18605 A6000-zyw
```

然后打开 `http://127.0.0.1:18605`。页面上的「青屿纪要」应返回种子材料 `LNSEED02`。导入新材料后，用系统给出的代号再检索，结果里应出现该代号。

命令行示例：

```sh
uv run --locked python tracks/05_qoder_database_tools/src/labnotes.py search --keyword 青屿纪要 --query 组会混合检索
uv run --locked python tracks/05_qoder_database_tools/src/labnotes.py import --title 临时核对 --topic 核对 --body 这是一条新的中文组会材料。
```

## 验证

`tests/test_labnotes.py` 会：

1. 写入不少于 10 条中文种子，并确认「青屿纪要」能被混合检索找到。
2. 导入一条新的中文材料，刷新索引后用它的独特代号检索，确认代号出现在 `hybrid_search` 结果中。
3. 拉起只绑定 `127.0.0.1:18605` 的服务，通过 HTTP 再做一次检索和导入。
4. 确认输出里没有数据库口令。

最近一次通过后的摘要写在 `results/hybrid_search.json`。该目录被上层 `.gitignore` 忽略，所以同一份摘要也写到 `docs/last_run.json`。步骤说明见 [docs/verification.md](docs/verification.md)，检索方式见 [docs/design.md](docs/design.md)。

早期课程笔记仍在 [docs/task.md](docs/task.md)，不是本服务的验收指标。正式题面里的公开网站要求目前被上面的 Qoder Sites blocked 挡住。

## 目录

| 路径 | 用途 |
| --- | --- |
| `src/labnotes.py` | 种子、导入、混合检索 |
| `src/server.py` | 只绑定 127.0.0.1:18605 的页面和接口 |
| `src/embeddings.py` | 本地哈希向量 |
| `src/seed_labnotes.json` | 中文种子材料 |
| `data/labnotes.json` | 运行时复制的种子 |
| `tests/test_labnotes.py` | 检索和绑定验证 |
| `results/` | 最近一次验证摘要 |
| `docs/` | 方案、验证说明和题面笔记 |
