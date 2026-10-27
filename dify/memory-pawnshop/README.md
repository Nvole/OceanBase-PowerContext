# 记忆当铺 · Memory Pawnshop

> 当掉一段小记忆，换一件不存在的失物。下次推门，掌柜阿当还记得你。

这是一个用 **Dify Chatflow + PowerContext** 做成的 AI 叙事小游戏。玩家把一段虚构、无害的小记忆当给当铺，掌柜会称重、估价，并编出一件与记忆暗中有联系的“不存在的失物”。换一个新会话后，只要带上同一个当票号，掌柜会从旧账里翻出之前的原话、失物和赎回条件。

## 为什么好玩

- 每次典当都会得到三样东西：一个荒诞的计量单位、一个非现实价格、一件只属于这段记忆的失物。
- 掌柜不是复读机。他会把旧失物、旧原话和当天的“柜台天气”揉进新回执。
- “赎回”不是真的删除数据，而是触发一段只读旧账叙事：掌柜会告诉你旧物现在过得怎么样，再开一个温柔但离谱的赎回条件。
- 当票号像一把旧抽屉钥匙。用户可以说“当票号：小满”，也可以完全不取名，让系统按 Dify 用户身份自动分配。

## 技术分工

| 组件 | 实际职责 |
| --- | --- |
| Dify Chatflow | 输入解析、8 节点流程编排、LLM 角色扮演、HTTP 工具调用、最终回复；提交文件为 `dify/Memory_Pawnshop_Chatflow.yml`。 |
| PowerContext 1.2.0 | 每个当票号对应一个 Scope；保存原始互动 Source 与 Memory entry；`entries/list`、`memory/search`、`context/prepare` 负责跨会话召回与有界上下文组装。 |
| Node 后端 | 零依赖适配层：当票号映射、意图判断、PowerContext 读写、安全脱敏、幂等和错误处理。它不替代 PowerContext 的记忆职责。 |

```text
Dify WebApp / API
        |
        |  Chatflow: 认领当票 -> HTTP 翻阅旧账 -> LLM 掌柜 -> HTTP 封存
        v
Node adapter  http://127.0.0.1:8765
        |
        |  Scope / Source / Memory / Search / Prepare
        v
PowerContext Server  http://127.0.0.1:8000
```

### Dify 流程

1. **开始**：Chatflow 不依赖自定义 Start 变量，直接接收 `sys.query`。
2. **认领当票**：Code 节点优先解析“当票号：小满”；没有显式名字时，用 `sys.user_id` 哈希出稳定的 `客-XXXXXXXXXX` 当票号。
3. **翻阅旧账**：HTTP 节点调用 `POST /api/pawn/context`，读取 PowerContext Scope、历史当票、搜索命中和 `context/prepare`。
4. **解析旧账**：Code 节点兼容 JSON 字符串或对象，拆出当票、访问次数、意图、掌柜情绪和旧账文本。
5. **掌柜阿当**：LLM 节点按角色提示词写新当票或翻旧账；模型可在导入后重新绑定。
6. **封存当票**：HTTP 节点调用 `POST /api/pawn/remember`；查询/赎回只读，不新增当票。
7. **解析回执**：Code 节点把真实写入结果转成读者可读的封存状态。
8. **把当票递给客人**：Answer 节点输出掌柜回执、PowerContext 写入状态和当票号提示。

## 目录

```text
outputs/memory-pawnshop/
├─ README.md
├─ dify/Memory_Pawnshop_Chatflow.yml   # 直接导入 Dify 的主产物
├─ backend/                            # 零依赖 Node 适配后端
├─ scripts/build_dsl.py                # 从源码重建 DSL（可选）
├─ scripts/validate_dsl.py             # DSL 结构与内嵌 Python 校验
├─ scripts/verify.mjs                  # 后端 + PowerContext 自动验收
├─ scripts/seed-demo.mjs               # 初始化一个可体验的旧账
├─ scripts/check-dify-prereqs.ps1      # 检查 Docker/WSL/Node/磁盘
├─ scripts/start-local-stack.ps1       # 启动并检查本地记忆栈
├─ scripts/setup-dify.ps1              # 下载（codeload zip，无需 git）并启动 Dify 1.9.x 容器
├─ scripts/package-submission.ps1      # 生成干净提交目录并扫描密钥
├─ data/                               # 运行后自动生成 ledger.json
├─ docs/DEMO.md                        # Dify 实机演示 Runbook
├─ docs/VALIDATION.md                  # 验证步骤与实测记录
└─ evidence/                           # 实际运行结果 JSON 与实机演示截图
```

## 环境与版本

- Dify：目标 **1.9.x**（实测 **1.9.2**，Docker Desktop + WSL2 本地部署），DSL `version: 0.3.1`；使用 Chatflow（`advanced-chat`）。
- PowerContext：**1.2.0**，参考 `oceanbase/powercontext` 的 `2026-competition-ecosystem` 分支。
- Node.js：**>= 22.5**（实测 24.22.1），后端零 npm 依赖。
- Python：3.11+（仅重建/校验 DSL 时需要；实测 3.12.14，依赖 PyYAML）。
- 模型：DSL 默认 `langgenius/openai/openai` + `gpt-4o-mini`。导入后必须绑定自己可用的 Chat 模型；不要求 Embedding/Rerank，PowerContext 当前使用其 FTS 召回。作者实机演示绑定 OpenAI 兼容供应商的 `deepseekv4pro`（第三方中转）。
- 端口：PowerContext `8000`，当铺后端 `8765`。两者均可通过环境变量调整。

## 启动步骤

以下命令以 Windows PowerShell 为例。Linux/macOS 只需替换虚拟环境路径与反引号命令。

### 1. 启动 PowerContext

在仓库根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install "powercontext[cli,server]==1.2.0"
New-Item -ItemType Directory -Force .\work\powercontext-data | Out-Null

$env:POWERCONTEXT_HOME = (Join-Path $PWD 'work\powercontext-data')
$env:POWERCONTEXT_SERVER_HTTP_PORT = '8000'
.\.venv\Scripts\powercontext.exe server run --no-env-file
```

另开终端确认：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health/live
Invoke-RestMethod http://127.0.0.1:8000/health/ready
```

`live=ok`、`ready=ready` 才算就绪。SQLite 足够本次作品的显式记忆读写；不要求配置生成或 Embedding 模型。

### 2. 启动当铺后端

```powershell
cd outputs\memory-pawnshop\backend
Copy-Item .env.example .env
node server.mjs
```

后端零依赖，不需要安装任何包。默认监听 `0.0.0.0:8765`，数据写入 `../data/ledger.json`。若本机已安装 npm，也可执行 `npm start`。

```powershell
Invoke-RestMethod http://127.0.0.1:8765/health
```

预期 `ok: true`，且 `powercontext.live: ok`。

也可以使用封装脚本；它默认把演示账本写到 `work/demo-data`，不会污染交付目录的 `data/`：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-local-stack.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\start-local-stack.ps1 -CheckOnly
```

### 3. 导入 Dify

1. 准备 Dify 1.9.x 和至少一个可用的 Chat 模型。本机没有 Dify 时，可先执行 `powershell -ExecutionPolicy Bypass -File .\scripts\setup-dify.ps1` 自动部署：脚本查询最新 1.9.x tag，用 GitHub codeload zip 下载到 `work/dify-src` 并 `docker compose up -d`，不需要安装 git；`-WebPort 8080` 可改端口。
2. 在 Dify 工作室选择 **导入 DSL**，导入 `dify/Memory_Pawnshop_Chatflow.yml`。
3. 打开应用，进入 **掌柜阿当** LLM 节点，把模型重新绑定为你的模型；若未安装 OpenAI 插件，先安装对应模型插件。
4. 检查两个 HTTP Request 节点的地址：
   - Dify 由 Docker Desktop 部署且与后端同机：保留 `http://host.docker.internal:8765`。
   - Dify 与后端同机原生部署：改为 `http://127.0.0.1:8765`。
   - Dify 云端或另一台机器：改为可公网访问的 HTTPS 地址，并保持路径 `/api/pawn/context`、`/api/pawn/remember`。
5. 若 Dify 启用 SSRF 防护，需要把后端主机加入允许列表；否则 HTTP 节点会拒绝内网地址。
6. 若设置了 `PAWNSHOP_API_KEY`，在两个 HTTP 节点增加请求头 `X-Pawnshop-Key: <同一个值>`。
7. 保存并发布应用，进入 Chatflow 预览或 WebApp 体验。

完整的 Dify 实机演示、截图清单和排错步骤见 [docs/DEMO.md](docs/DEMO.md)。

## 玩法与当票号

### 显式取名

在任意消息里写：

```text
当票号：小满。我想当掉一段关于小学门口辣条和一把断尺的记忆。
```

Code 节点会提取 `小满`。新会话里再次写 `当票号：小满。我上次当掉的东西，现在怎么样了？`，即可读回旧账。

### 自动当票号

没有写“当票号：…”时，系统根据 `sys.user_id` 生成稳定的 `客-XXXXXXXXXX`。每次回复末尾都会显示当前当票号，复制它到新会话即可。

### 三次点击就能看懂

1. 新会话输入：`当票号：小满。我想当掉一段关于小学门口辣条和一把断尺的记忆。`
2. 查看掌柜给出的称重、估价、失物和封存回执。
3. 新开会话输入：`当票号：小满。我上次当掉的东西，现在怎么样了？`
4. 再输入：`当票号：小满。我想赎回上次那把只量过身高的断尺。`

第 3、4 步都是只读旧账，不会新增当票。

### 预置演示旧账

如果想让评审一进入就有东西可查，可在后端运行后执行：

```powershell
cd outputs\memory-pawnshop\backend
node ..\scripts\seed-demo.mjs 演示-小满
```

然后在 Dify 新会话里输入：

```text
当票号：演示-小满。我上次当掉的东西，现在怎么样了？
```

## 接口

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/health` | 后端与 PowerContext 健康状态。 |
| `POST` | `/api/pawn/context` | 认出当票、读取旧账、搜索并组装 PowerContext 上下文。 |
| `POST` | `/api/pawn/remember` | 写入 Source 和 Memory；查询/赎回只返回只读回执。 |
| `GET` | `/api/pawn/ledger?ticket_id=...` | 查看当票摘要与最近 turn，不返回完整记忆正文。 |

本地台账只负责当票号到 PowerContext Scope 的映射、turn 状态和幂等回放；原始记忆正文和召回结果来自 PowerContext。

## 验证

### 一键后端验收

保持 PowerContext 和后端运行：

```powershell
cd outputs\memory-pawnshop\backend
node ..\scripts\verify.mjs
```

该脚本用两个不同 `conversation_id` 模拟 Dify 的两次会话，覆盖 28 项检查：

- 首次典当写入 PowerContext，返回 `scope_id` 与 `mem_ent_...` citation。
- 同一 turn 重复封存命中幂等，不重复计数。
- 新会话通过 `memory/search` 和 `entries/list` 召回旧失物与旧原话。
- 查询/赎回只读，不新增当票。
- 邮箱、手机号在写入 PowerContext 前被替换。

结果写入 `evidence/verify-latest.json`。详细步骤和实测值见 [docs/VALIDATION.md](docs/VALIDATION.md)。

### DSL 校验

```powershell
cd outputs\memory-pawnshop
py -m pip install pyyaml
py scripts\validate_dsl.py
```

脚本检查 8 节点拓扑、变量引用、HTTP 配置、内嵌 Python 可编译性、当票号解析和 Dify 用户兜底逻辑，结果写入 `evidence/dsl-validation.json`。

### Dify 前置检查与提交打包

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\check-dify-prereqs.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\package-submission.ps1
```

打包默认输出到 `work/submission/memory-pawnshop/`，会排除 `.env`、`ledger.json`、`node_modules`、`__pycache__` 等运行时文件，扫描常见密钥格式并生成 `SUBMISSION_MANIFEST.json`。

本次实测：**28 项后端/PowerContext 检查通过，62 项 DSL 检查通过；Dify 1.9.2 实机三轮演示通过（当票号 `小满`，账本 1 张当票），截图见 `evidence/screenshots/`**。

### 已验证范围

- PowerContext 1.2.0 真实启动、Scope 创建、Source 写入、Memory 写入、`entries/list`、`memory/search`、`context/prepare` 均实测通过。
- 后端与 PowerContext 的跨会话闭环实测通过；原始测试原话“小学门口辣条”和失物“一把只量过身高的断尺”能在新会话召回。
- Dify 1.9.2 实机导入与三轮 LLM 对话实测通过（2026-10-28）：新会话召回旧原话与旧失物、赎回只读不新增当票；账本快照见 `evidence/dify-demo-ledger.json`，截图见 `evidence/screenshots/`。评审按本文步骤即可复现；DSL 内的模型与 HTTP 地址都保留了可重新绑定入口。

## 数据与恢复

- 首次启动后端会自动创建 `data/ledger.json`，初始为空。该文件只保存当票映射和 turn 状态，不保存完整记忆正文。
- PowerContext 的记忆存储在 `POWERCONTEXT_HOME` 指向的目录，本次实测为 `work/powercontext-data/powercontext.db`。
- 若要重新开始，先停止后端与 PowerContext，再删除明确指定的 `data/ledger.json` 和 PowerContext 数据目录；两个服务重启后会重新初始化。不要删除 Dify 自身数据库。
- 当票号相当于访问旧账的钥匙，不要把它和真实隐私一起使用。

## 比赛仓库提交位置

按赛题要求，将 `outputs/memory-pawnshop/` 整体放入 `oceanbase/powercontext` 的 `2026-competition-ecosystem` 分支 `dify/` 目录下，例如：

```text
powercontext/
└─ dify/
   └─ memory-pawnshop/
      ├─ README.md
      ├─ dify/Memory_Pawnshop_Chatflow.yml
      ├─ backend/
      ├─ scripts/
      ├─ docs/
      └─ evidence/
```

不要提交 `backend/.env`、真实 Token 或运行时生成的 `data/ledger.json`；它们已写入 `.gitignore`。

## 隐私与已知限制

- 应用只适合放虚构、无害的小记忆；提示词和 README 都明确禁止密码、证件、住址、联系方式或他人隐私。
- 后端对常见手机号、邮箱、证件号、密钥和 Bearer Token 做写入前替换，但这是基础防护，不是完整 DLP。
- PowerContext 默认 FTS 对极短中文查询可能召回不足，因此后端会把检索词扩展为“原查询 + 当票 失物 记忆”。
- PowerContext 不可达时，后端返回 `502`，Dify 会显示节点错误，不会伪造一段“记得”的假记忆。
- 若 Dify HTTP 节点无法访问 `host.docker.internal`，优先检查 Dify 容器网络、SSRF 白名单和端口；不要误把 `127.0.0.1` 当作容器内的后端地址。
- PowerContext 1.2.0 的 `POST /v1/scopes` 不要传空以外的 `context_references`；本实现已移除该字段，以避免 `404 scope_not_found`。

## 常见问题

| 现象 | 处理 |
| --- | --- |
| `/health` 显示 PowerContext unavailable | 确认 `http://127.0.0.1:8000/health/ready` 为 ready，并检查 `POWERCONTEXT_URL`。 |
| Dify 报 HTTP 节点连接失败 | Docker 部署用 `host.docker.internal`；原生部署用 `127.0.0.1`；云端用 HTTPS 隧道。 |
| Dify 报 SSRF/内网地址被拒绝 | 在 Dify 的 SSRF 配置中允许后端主机，或使用公网 HTTPS 地址。 |
| 导入后 LLM 节点不可用 | 安装对应模型插件，并在“掌柜阿当”节点重新绑定模型。 |
| 新会话没有旧账 | 先在第一次回复末尾复制当票号；新会话必须带上同一个“当票号：…”。 |
| 召回命中了但掌柜没提旧细节 | 确认 LLM 看到的是旧账 memory block；可先用 `curl` 调 `/api/pawn/context` 核对 `memory_block`。 |

## 参考

- 赛题与提交要求：<https://oceanbase.yuque.com/org-wiki-obtech-vh7w9r/hc3pio/lhfslihtnnb8yqh6>
- PowerContext 仓库：<https://github.com/oceanbase/powercontext/tree/2026-competition-ecosystem>
- PowerContext 接口文档：<https://powercontext.oceanbase.io/zh/docs/develop/interfaces/>
- Dify 应用导入/导出：<https://docs.dify.ai/en/cloud/use-dify/workspace/app-management>
