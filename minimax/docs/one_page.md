# 一页技术说明

## 模块

- `src/lab/invoice_filter.py`：发票筛选。金额和状态原本可用；本次补上闭区间日期。
- `src/sdd_context`：导入资料、按任务检索、组装上下文、读写任务状态、在有 key 时调用 MiniMax。
- 入口：`python -m sdd_context`，子命令 `import`、`build`、`save-state`、`show-state`。

## 上下文怎么选

`build --task` 把任务文本切成检索词，对 collection `track07_sdd_docs` 做 `where_document.$contains`。命中的文档正文和 metadata.source 直接进入规格、代码、测试三组。检索模块不写死资料文件名。改规格句子后若不重新导入，输出仍是库里的旧句子；重新导入后输出新句子。

## 技术分工

| 组件 | 作用 | 版本与接入 |
| --- | --- | --- |
| seekdb | 保存并检索规格、代码、测试 | 现有 `127.0.0.1:2881`，pyseekdb collection API |
| PowerContext | 保存已完成事项、待办和验证结论；重启后再读并放进上下文 | 1.4.0，HTTP `127.0.0.1:18617`，SQLite 基础记忆 |
| MiniMax | 接收上述上下文并修改代码 | 有 `MINIMAX_API_KEY` 才调用；否则不编造对话 |

业务发票不进 seekdb。seekdb 里是工程资料。PowerContext 不替代资料库。
