# 离谱许愿池 · The Absurd Wishwell

> 向废弃喷泉投一枚离谱愿望，池神会翻出 seekdb 里的旧愿望，给你写一封温柔又离谱的回声信。

这是为「Just for Fun——用 Dify 做一个好玩的智能应用」赛题制作的 Dify + seekdb 作品。玩家许一个愿（越离谱越好），池神先用 seekdb 在旧账里做一次 hybrid search，找出最像的旧愿望，再写一封引用它们的回声信，并盖一枚许愿币编号；最后愿望与回声被写回池子，成为下一位许愿人的回声。

## 为什么好玩

- 换新会话、换陌生人，旧愿望都会浮上来回响你的新愿望——跨会话记忆变成玩法本身。
- 每次投币得到三样东西：应验概率、离谱指数、一件不存在的赠品。
- 池神不是复读机：他会引用旧许愿人的原话，把两枚不相干的愿望编成邻居。
- 许愿币编号（W-xxxxxxxx）像旧抽屉钥匙，可以在 `results/sample_run.json` 里查到自己留下的回声。

## 技术分工

| 组件 | 实际职责 |
| --- | --- |
| Dify DSL `docs/wishwell.dsl.yml` | 核心流程编排：输入 → HTTP 检索 → LLM 池神 → 代码制币 → HTTP 保存 → 输出。DSL 版本 0.5.0（Dify 1.12+）。 |
| seekdb `track04_wishwell` | 愿望与回声的唯一存储；每次投币一次 `hybrid_search`（64 维特征哈希向量 + IK 全文，RRF 融合），写入后 `refresh_index`。 |
| HTTP 服务 `src/server.py` | 只监听 `127.0.0.1:18604`，对 Dify 暴露 `/v1/toss`（检索）与 `/v1/keep`（保存）。 |
| `src/hashvec.py` | 标准库实现的 64 维特征哈希向量，不依赖模型与 Embedding 服务。 |

```text
Dify Workflow
   |  投币: HTTP POST /v1/toss（seekdb hybrid_search）
   |  池神: LLM 写回声信
   |  入池: HTTP POST /v1/keep（seekdb upsert + refresh_index）
   v
src/server.py  http://127.0.0.1:18604
   |
   v
seekdb collection track04_wishwell  (127.0.0.1:2881)
```

## 目录

```text
dify/
├─ README.md
├─ .env.example
├─ docs/wishwell.dsl.yml      # Dify 1.12+ DSL 0.5.0（提交版）
├─ docs/wishwell-dify-1.9.x.yml  # 本地 Dify 1.9.x 演示变体（0.3.1，由脚本生成）
├─ docs/运行说明.md
├─ src/server.py              # HTTP 服务（127.0.0.1:18604）
├─ src/wishwell.py            # seekdb collection 与 hybrid 检索
├─ src/poolgod.py             # 池神确定性回声（无模型环境）
├─ src/hashvec.py             # 64 维特征哈希向量
├─ src/play_wish.py           # 按 DSL 顺序打完整一局
├─ data/seed_wishes.json      # 预置愿望
├─ data/sample_input.json     # 样例输入
├─ tests/test_wishwell.py     # 单测 + 真实 seekdb 检查 + DSL 一致性
├─ scripts/validate_dsl.py      # DSL 结构校验
├─ scripts/build_local_variant.py  # 生成 1.9.x 本地变体
└─ results/                   # test_report.json / sample_run.json / dsl-validation.json
```

## 运行

评测机（seekdb 默认模式）：见 [docs/运行说明.md](docs/运行说明.md)。

```sh
cd ~/oceanbase
. ./env.sh
uv run --locked python tracks/04_dify_workflows/tests/test_wishwell.py
uv run --locked python tracks/04_dify_workflows/src/play_wish.py
```

本地没有 seekdb 时可用文件替身体验（`WISHWELL_STORE=file`），接口一致，仅作演示与单测，不作为比赛存储。本机 Dify 1.9.x 可导入 `docs/wishwell-dify-1.9.x.yml` 体验同一条工作流。

## 验证样例

1. 投币：`{"player": "试池的人", "wish": "我想许愿周五永远不结束，并且食堂的鸡腿每天多一根。"}`
2. 预期：`/v1/toss` 返回 `seekdb_hybrid_rrf` 融合的旧愿望 hits；池神回声引用旧愿望、给出应验概率与离谱指数、附赠品与许愿币编号。
3. 入池：`/v1/keep` 返回 `w_<coin>`、`e_<coin>`、`refreshed: true`。
4. 回声：用相近句子再投币，能召回自己的许愿币——seekdb 读写闭环。
5. 证据：`results/test_report.json`（测试清单）与 `results/sample_run.json`（完整一局）。

## 复用来源与改动

- seekdb 接入方式（`connect_collection_api`、`hybrid_search` + RRF、`upsert` + `refresh_index`）沿用本仓库 Dify 赛题目录的既有约定。
- 特征哈希向量思路参考同仓库 `src/hashvec.py` 的公开实现，常量与分词逻辑为本项目重写。
- `pyseekdb==1.4.0.post1` 用法参考 [seekdb 官方文档](https://docs.seekdb.ai/seekdb/pyseekdb-sdk-get-started)。

## 已知限制

- 回声信的文学质量取决于所绑定的模型；无模型环境下由 `poolgod.py` 提供确定性回声。
- 64 维哈希向量仅适合这个小游戏，不能当作通用语义嵌入。
- 重复投同一愿望会 upsert 同一 id，不会无限加行。
- 应用只适合放虚构、无害的愿望。