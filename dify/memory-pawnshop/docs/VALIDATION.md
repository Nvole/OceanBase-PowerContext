# 验证与运行证据

## 结论

最近一次完整验证：**2026-10-28**（自动验收完成于 2026-10-27，Dify 1.9.2 实机演示完成于 2026-10-28）。

| 验证对象 | 结果 | 证据 |
| --- | --- | --- |
| Node 后端 + PowerContext 1.2.0 跨会话记忆闭环 | **28/28 通过** | `evidence/verify-latest.json` |
| Dify DSL 结构、变量、内嵌 Python、HTTP body 与当票号解析 | **62/62 通过** | `evidence/dsl-validation.json` |
| Dify 1.9.2 实机导入与三轮 LLM 对话 | **已通过（2026-10-28 实测）** | `evidence/screenshots/`、`evidence/dify-demo-ledger.json` |

## 实测环境

- Windows 11，PowerShell，Docker Desktop 29.9.2（WSL2 引擎）。
- Node.js 24.22.1。
- Python 3.12.14（仅 DSL 生成/校验）。
- PowerContext 1.2.0，接口 `http://127.0.0.1:8000`。
- 当铺后端 `http://127.0.0.1:8765`。
- Dify 1.9.2，本地 Docker 部署（`scripts/setup-dify.ps1` 下载到 `work/dify-src`，`docker compose up -d`，Web 端口 80）。
- Dify 演示模型：OpenAI 兼容供应商的 `deepseekv4pro`（第三方中转，仅作者环境演示绑定用）。
- 自动验收时 Dify 的 LLM 回复使用确定性测试文本，以便单独验证后端与 PowerContext；Dify 实机演示的掌柜回复由真实 LLM（`deepseekv4pro`）生成。

## 实际记录

本次验收使用当票号 `验收-mvqjb6yv`：

- 首次当票：`MP-A8A-001`
- 失物：`一把只量过身高的断尺。`
- PowerContext Scope：`scp_6eh0nk9exs5mjg70se6nj8hp7r`
- Memory entry：`mem_ent_02219690a18c4c11b8e8b934e100ee51`
- 第二次会话 `search_hits = 1`，`context_status = ready`
- 只读查询后账本仍为 `ticket_count = 1`
- 脱敏测试替换 2 处（邮箱、手机号）

新会话实际读回的 `memory_block` 包含：

```text
本次到访：第 2 次
是否回访：是，账本里有旧当票
最近一件失物：一把只量过身高的断尺。

【最近封存的当票】
- 当票 MP-A8A-001｜客人说：我想当掉一段关于小学门口辣条和一把断尺的记忆。
```

这证明旧原话和旧失物不是从本地台账硬编码出来的：它们来自 PowerContext 的 Memory entry，并通过 `entries/list`、`memory/search` 与 `context/prepare` 进入 Dify 的 memory block。

## Dify 实机演示记录（2026-10-28）

Dify 1.9.2 由 `scripts/setup-dify.ps1` 通过 GitHub codeload zip 部署到 `work/dify-src`（无需 git），`docker compose up -d` 启动 11 个容器，Web 端口 80。导入 `dify/Memory_Pawnshop_Chatflow.yml` 后，将「掌柜阿当」LLM 节点绑定为 OpenAI 兼容供应商的 `deepseekv4pro`，两个 HTTP 节点保留 `http://host.docker.internal:8765`。

用当票号 `小满` 完成三轮演示，账本快照见 `evidence/dify-demo-ledger.json`：

| 轮次 | 输入 | 结果 |
| --- | --- | --- |
| 1 | 典当「小学门口辣条和一把断尺」的记忆 | 生成当票 `MP-A18-001`、编出失物，PowerContext 封存成功 |
| 2 | 新会话问「我上次当掉的东西，现在怎么样了？」 | 召回旧原话与旧失物，回复标注“本次只翻阅旧账，没有封存新当票” |
| 3 | 新会话请求赎回 | 只读赎回叙事，不新增当票 |

结束后 `GET /api/pawn/ledger?ticket_id=小满` 返回 `ticket_count = 1`、`visits = 3`，证明跨会话召回与只读约束在真实 Dify 流程中成立。截图：`evidence/screenshots/01-dify-recall-turn2.png`、`02-dify-recall-turn2-detail.png`、`03-dify-redeem-turn3.png`。

## 复现自动验收

### 前置

1. 按 README 启动 PowerContext 和后端。
2. 确认以下两项正常：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health/ready
Invoke-RestMethod http://127.0.0.1:8765/health
```

### 执行

```powershell
cd outputs\memory-pawnshop\backend
node ..\scripts\verify.mjs
```

预期最后输出 `验收通过`，并刷新 `evidence/verify-latest.json`。验证脚本会自动生成唯一当票号，不会覆盖已有用户数据。

### 检查项

脚本按顺序检查：

1. 后端与 PowerContext 健康。
2. 首次到访识别为 `pawn`，访问次数为 1，没有伪造旧账。
3. Scope 创建成功，PowerContext 返回 `scope_id`。
4. 首次封存成功，失物提取正确，返回 `mem_ent_...` citation。
5. 重复封存同一 turn 命中幂等回放，entry ID 不变。
6. 使用不同 `conversation_id` 发起第二次查询，识别为 `recall` 和回访。
7. memory block 包含旧失物与旧原话，搜索有命中。
8. 查询/赎回只读，账本数量不变。
9. 邮箱/手机号在写入前脱敏，重新读取旧账看不到原文。

## Dify DSL 校验

```powershell
py -m pip install pyyaml
py scripts\validate_dsl.py
```

本次结果：

- DSL SHA-256：`6daa36064c54225df6cfbc368078ce5ae58d7c57701742bde0ef91da495a6510`
- 节点：`start -> identify_ticket -> http_context -> parse_context -> llm -> http_save -> parse_save -> answer`
- Start 节点 `variables: []`，不依赖 Chatflow 中不存在的自定义输入。
- 两个 HTTP 节点为 POST + JSON，路径分别为 `/api/pawn/context`、`/api/pawn/remember`。
- 所有内嵌 Python 节点可编译。
- 当票号解析通过显式、引号、URL 拒绝、24 字符上限和 Dify 用户稳定兜底测试。

## Dify 内体验步骤

以下步骤已于 2026-10-28 在 Dify 1.9.2 上完整执行，结果见上一节。

1. 导入 `dify/Memory_Pawnshop_Chatflow.yml`，重新绑定 LLM 模型。
2. 确认 HTTP 节点可从 Dify 访问后端。
3. 新会话输入：`当票号：小满。我想当掉一段关于小学门口辣条和一把断尺的记忆。`
4. 记录回复末尾的当票号与掌柜编出的失物。
5. 新开会话输入：`当票号：小满。我上次当掉的东西，现在怎么样了？`
6. 预期掌柜提到旧失物和旧原话，并在末尾显示“本次只翻阅旧账，没有封存新当票”。
7. 再输入：`当票号：小满。我想赎回上次那把只量过身高的断尺。`
8. 预期仍不新增当票；可在 `GET /api/pawn/ledger?ticket_id=小满` 中核对 `ticket_count` 没有增加。

## 未覆盖项

- 实机演示为截图留证，未录制屏幕录像；评审可在任何装有 Dify 1.9.x 的机器上按上文步骤复现。
- 演示使用的 `deepseekv4pro` 是第三方中转模型，只用于作者环境；评审导入 DSL 后需绑定自己的模型。
- 记忆正文的语义质量依赖所绑定的 LLM；自动验收使用固定回复，只验证流程与 PowerContext 数据闭环。

