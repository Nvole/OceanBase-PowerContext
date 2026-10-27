# 运行证据说明

本目录保存可机器读取的验收结果，不包含伪造截图。

| 文件 | 内容 |
| --- | --- |
| `verify-latest.json` | Node 后端 + PowerContext 1.2.0 的端到端验收：28 项检查、Scope/Entry citation、跨会话召回文本、幂等、只读和脱敏。 |
| `dsl-validation.json` | Dify DSL 结构、节点拓扑、变量引用、HTTP body 格式、内嵌 Python 编译和当票号解析的 62 项检查。 |
| `screenshots/01-dify-recall-turn2.png` | Dify 1.9.2 实机第二轮：新会话召回旧原话与旧失物。 |
| `screenshots/02-dify-recall-turn2-detail.png` | 第二轮回复细节，含“本次只翻阅旧账，没有封存新当票”。 |
| `screenshots/03-dify-redeem-turn3.png` | 第三轮赎回：只读叙事，不新增当票。 |
| `screenshots/recall-turn.png` | 召回回复的补充截图，可与 01/02 互证。 |
| `dify-demo-ledger.json` | 三轮演示后的账本快照：`ticket_count = 1`、`visits = 3`、最后当票 `MP-A18-001`。 |

## 关键实测值

- 当票号：`验收-mvqjb6yv`
- 当票：`MP-A8A-001`
- PowerContext Scope：`scp_6eh0nk9exs5mjg70se6nj8hp7r`
- Memory entry：`mem_ent_02219690a18c4c11b8e8b934e100ee51`
- 新会话搜索命中：`1`
- 旧失物召回：`一把只量过身高的断尺。`
- 旧原话召回：`我想当掉一段关于小学门口辣条和一把断尺的记忆。`
- 只读查询后当票数：`1`
- 脱敏：邮箱、手机号共 2 处

## 如何复现

启动 PowerContext 与后端后，在 `backend` 目录执行：

```powershell
node ..\scripts\verify.mjs
```

如需重新校验 DSL：

```powershell
py ..\scripts\validate_dsl.py
```

## 边界

`verify.mjs` 模拟 Dify 的两次会话请求，掌柜回复使用确定性测试文本，用于单独验证 Dify 之后的调用链。Dify UI 部分已由 2026-10-28 的实机演示覆盖（Dify 1.9.2 + `deepseekv4pro`）：三轮对话、跨会话召回与只读赎回均有截图与账本快照，见 `screenshots/` 与 `dify-demo-ledger.json`。

