# 运行说明

## 环境

在 A6000 项目根目录执行，不安装系统包，不拉取镜像，不重启 `127.0.0.1:2881`。

- 项目根：`/data/zouyuanwei/oceanbase`
- Python：项目 uv 环境，CPython 3.11
- seekdb：已有服务 `127.0.0.1:2881`，本题账号见本目录 `.env`（权限 600，不要提交）
- pyseekdb 1.4.0.post1，PyMySQL 1.2.3
- PowerContext 1.4.0：本题目录 `.powercontext/venv`，只监听 `127.0.0.1:18617`，SQLite 放在 `.powercontext/home`
- MiniMax：仅当环境变量 `MINIMAX_API_KEY` 存在时调用 `https://api.minimaxi.com/v1/text/chatcompletion_v2`，默认模型为 `MiniMax-M3.1-Flash`。没有该变量时不编造对话

`.env` 只保存 seekdb 连接。不要把 MiniMax key 写进仓库。

## 初始化与验证

```sh
cd /data/zouyuanwei/oceanbase
. ./env.sh
uv run --locked python tracks/07_minimax_engineering_context/tests/run_verification.py
```

该命令会：

1. 用修改前快照跑同一组测试，把失败日志写到 `results/tests_before.txt`。
2. 恢复日期范围实现后再跑，写到 `results/tests_after.txt`。
3. 把规格、代码和测试导入 seekdb collection `track07_sdd_docs`。
4. 用查询结果组装上下文，修改规格句子后重新导入并核对新句子，然后把规格恢复。
5. 在 PowerContext 写入任务状态，重启服务后再读，并放进下一次上下文。

只跑功能测试：

```sh
cd /data/zouyuanwei/oceanbase
. ./env.sh
PYTHONPATH=tracks/07_minimax_engineering_context/src \
  uv run --locked python -m unittest discover \
  -s tracks/07_minimax_engineering_context/tests -v
```

单独重建上下文：

```sh
cd /data/zouyuanwei/oceanbase
. ./env.sh
export PYTHONPATH=tracks/07_minimax_engineering_context/src
uv run --locked python -m sdd_context import
uv run --locked python -m sdd_context build --task "invoice-date-range filter_invoices test_filter_by_date_range SPEC_SENTENCE 日期范围 金额 状态"
uv run --locked python -m sdd_context show-state
```

`build` 的来源取自 collection 命中的 `source`，不在代码里写死资料文件名。规格文件约定为 `docs/*_spec.md`。

## 重置

- 发票数据是 `data/invoices.json`，筛选函数不写数据库。
- 重新导入：`python -m sdd_context import`。
- 修改前代码在 `results/invoice_filter.before.py`。验证脚本会临时换上它，结束时恢复 `src/lab/invoice_filter.py`。
- PowerContext 状态在 `.powercontext/home`。验收脚本每次从空库重新写入。

## 已知限制

- 向量是稳定的词桶，不是语义嵌入模型。选材以全文检索为准。
- PowerContext 使用基础记忆，没有单独的生成模型，因此不会自动摘要。
- 没有 `MINIMAX_API_KEY` 时，MiniMax 记为 blocked。
- 若 18617 被其他进程占用，或 PowerContext 起不来，状态复用记为 blocked，不用 seekdb 表冒充。
