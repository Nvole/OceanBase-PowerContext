# 阶跃星辰：浏览器端知识库

浏览器在本机用 Transformers.js 计算 INT8 embedding，seekdb 保存原文和向量，并用 `hybrid_search` 做全文加向量混合检索。服务端不计算 embedding。

题意见 [docs/task.md](docs/task.md)。模型、量化和检索说明见 [docs/technical_note.md](docs/technical_note.md)。

数据库账号是 `track02_stepfun`，连接信息在本目录权限 600 的 `.env`。不要提交 `.env`，不要打印密码，不要重启 `127.0.0.1:2881` 上的 seekdb。

## 启动

在 A6000 上，seekdb 已经监听 `127.0.0.1:2881` 时：

```sh
cd /data/zouyuanwei/oceanbase
. ./env.sh
uv run --locked python tracks/02_stepfun_browser_kb/tests/test_fixed_vectors.py
uv run --locked python tracks/02_stepfun_browser_kb/src/server.py
```

服务只绑定 `127.0.0.1:18602`。在自己的电脑上另开一个终端做转发，再用 Chrome 或 Edge 打开：

```powershell
ssh -N -L 18602:127.0.0.1:18602 A6000-zyw
```

浏览器访问 `http://127.0.0.1:18602`。模型权重由浏览器向 Hugging Face 下载，这是文件下载，不是云端推理 API。无 WebGPU 时页面会显示已降级到 WASM。

## 页面上做什么

1. 确认顶部显示当前推理后端：WebGPU 或 WASM，以及 INT8 / dtype q8。
2. 导入示例语料。向量在浏览器里分批算出，服务端写入集合 `track02_stepfun_kb` 后调用 `refresh_index`。
3. 输入查询。查询向量仍在浏览器计算，检索由 seekdb 的 `hybrid_search` 完成。
4. 需要时追加一段原文，或勾选只检索当前会话。
5. “固定向量探针”不加载模型，用预设单位向量检索关键词 `webgpufirst`。它只证明数据库链路，不代替端侧推理。
6. “实测批处理与逐条编码”和“用当前后端跑固定问题”只显示这次浏览器真正测到的数字。

固定向量测试会重建 `track02_stepfun_kb` 并留下夹具文档。演示前可以在页面上清空集合。

## 目录

| 路径 | 内容 |
|---|---|
| `src/server.py` | 页面和 seekdb 网关，不含模型 |
| `src/kb.py` | 集合、写入、`refresh_index`、`hybrid_search` |
| `src/static/` | Transformers.js INT8 推理页面和 Worker |
| `data/corpus.jsonl` | 8 条示例原文，不含向量 |
| `data/fixed_vectors.json` | 测试写出的固定向量 |
| `data/eval_queries.json` | 浏览器可选对照问题 |
| `results/fixed_vector_test.json` | 数据库排序和耗时 |
| `results/model_artifact_sizes.json` | 公布的 ONNX 体积和压缩比 |

共享 Python 环境使用项目根目录的 uv。不要为这道题占用 GPU。
