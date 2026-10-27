# Dify 实机演示 Runbook

这份 Runbook 用于把「记忆当铺」从已完成的 DSL 变成可截图、可复现的 Dify 实机演示。按顺序执行即可；每一步都给出了预期结果和留证位置。

## 当前状态

- **Runbook 已在 2026-10-28 完整执行完毕**：Dify 1.9.2 实机三轮演示通过，截图归档于 `evidence/screenshots/`，账本快照为 `evidence/dify-demo-ledger.json`。
- 演示环境：Docker Desktop 29.9.2（WSL2 引擎）+ Dify 1.9.2（Web 端口 80）+ OpenAI 兼容模型 `deepseekv4pro`。
- PowerContext 与当铺后端的健康检查已实测为 `ready`。
- 本文件保留完整步骤，供评审在任何机器上复现；完成后的证据清单见第 5 节。

## 0. 前置检查

在作品目录执行：

```powershell
cd C:\Users\xujin\Documents\Codex\2026-10-27\just-for-fun-dify-90-5\outputs\memory-pawnshop
powershell -ExecutionPolicy Bypass -File .\scripts\check-dify-prereqs.ps1
```

期望看到 Docker、WSL、Node.js、Python 和磁盘空间检查（作者环境已通过该检查）。若 Docker/WSL 未就绪，先在管理员 PowerShell 中执行：

```powershell
wsl --install
```

重启 Windows 后安装 Docker Desktop，并确认 Docker Desktop 已启动。Dify 的镜像、数据库和模型调用缓存建议至少预留 20 GB。

## 1. 启动 Dify 1.9.x

```powershell
git clone https://github.com/langgenius/dify.git
cd dify
git checkout 1.9.x   # 使用仓库实际存在的 1.9 最新 tag
cd docker
Copy-Item .env.example .env
docker compose up -d
```

> 本机没有安装 Git 时，跳过上面的 `git clone`，直接使用封装脚本：脚本通过 GitHub API 取最新 1.9.x tag，再用 codeload zip 下载解压到 `work/dify-src`，不依赖 git（作者环境即用此方式）。

打开 `http://localhost/install` 创建管理员账号。若 80 端口被占用，在 `docker/.env` 中修改 `EXPOSE_NGINX_PORT=8080`，再访问 `http://localhost:8080/install`。

也可以用封装脚本自动完成“找 tag → 克隆 → 启动 → 等待就绪”：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup-dify.ps1
# 80 端口被占用时：powershell -ExecutionPolicy Bypass -File .\scripts\setup-dify.ps1 -WebPort 8080
# GitHub 拉取慢时：powershell -ExecutionPolicy Bypass -File .\scripts\setup-dify.ps1 -UseMirror
```

在 **Settings → Model Provider** 中配置至少一个 Chat 模型。推荐使用 OpenAI-compatible 服务，记录实际使用的 Provider、模型名和 API Base。

## 2. 启动本地记忆栈

在作品目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-local-stack.ps1
```

脚本会复用已经在运行的服务；如果未运行，则在后台启动 PowerContext 和后端。演示账本默认写入 `work/demo-data`，不会污染交付目录的 `data/`。随后手动确认：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health/ready
Invoke-RestMethod http://127.0.0.1:8765/health
```

期望 `ready`，且后端返回 `ok: true` 和 `powercontext.ready: ready`。

## 3. 导入 DSL 并联通 HTTP 节点

1. 在 Dify 中选择 **Studio → Import DSL**，导入 `dify/Memory_Pawnshop_Chatflow.yml`。
2. 打开 Chatflow，在 **掌柜阿当** LLM 节点重新绑定模型。
3. 检查两个 HTTP Request 节点：
   - Docker Desktop 与后端同机：保留 `http://host.docker.internal:8765`。
   - Dify 原生部署与后端同机：改为 `http://127.0.0.1:8765`。
   - Dify 在其他机器或云端：改为可访问的 HTTPS 地址。
4. 从 Dify 容器内确认后端可达：

```powershell
cd <dify-repo>\docker
docker compose exec api curl -s http://host.docker.internal:8765/health
```

如果 curl 不存在，可改用：

```powershell
docker compose exec api python -c "import urllib.request; print(urllib.request.urlopen('http://host.docker.internal:8765/health').read().decode())"
```

若报 SSRF/内网地址被拒绝，按 Dify 版本的 SSRF 配置允许该主机；不要简单地把地址改成容器内的 `127.0.0.1`。

## 4. 三轮完整演示

所有对话必须在同一个 Dify 应用中进行；第二轮开始使用 **New Chat / 新会话**，但保留同一个当票号。

| 步骤 | 输入 | 预期表现 | 留证 |
| --- | --- | --- | --- |
| 1 | `当票号：小满。我想当掉一段关于小学门口辣条和一把断尺的记忆。` | 生成当票号、荒诞称重、估价和一件失物；显示 PowerContext 封存成功 | 回复全文、运行历史 |
| 2 | `当票号：小满。我上次当掉的东西，现在怎么样了？` | 新会话召回旧原话与旧失物；“本次只翻阅旧账，没有封存新当票” | 旧物被提到的截图 |
| 3 | `当票号：小满。我想赎回上次那把只量过身高的断尺。` | 只读赎回叙事，不新增当票 | 账本数量仍为 1 |

第三轮的失物名称以第一轮实际生成结果为准；如果 LLM 把失物改写成了别的物件，把提示词里的“断尺”替换成实际名称。

本次实测（2026-10-28，当票号 `小满`）：

- 第 1 轮生成当票 `MP-A18-001`，失物与当票回执正常，PowerContext 封存成功；
- 第 2 轮新会话召回旧原话与旧失物，末尾出现“本次只翻阅旧账，没有封存新当票”；
- 第 3 轮赎回为只读叙事，不新增当票；
- 三轮后账本 `ticket_count = 1`、`visits = 3`，快照见 `evidence/dify-demo-ledger.json`。

### 账本只读检查

```powershell
$ticket = [uri]::EscapeDataString('小满')
Invoke-RestMethod "http://127.0.0.1:8765/api/pawn/ledger?ticket_id=$ticket" | ConvertTo-Json -Depth 5
```

期望 `ticket_count` 为 `1`。若为 `0`，说明第一轮没有成功写入；先查看 Dify HTTP 节点和 PowerContext 日志。

## 5. 采集证据

建议至少保存以下文件到 `evidence/screenshots/`（作者环境已归档 `01-dify-recall-turn2.png`、`02-dify-recall-turn2-detail.png`、`03-dify-redeem-turn3.png`）：

1. Dify 8 节点 Chatflow 全图（能看到两个 HTTP 节点）。
2. LLM 节点已绑定模型的截图。
3. 第一轮完整回复。
4. 新会话召回旧失物和旧原话。
5. 第三轮赎回回复。
6. Dify 运行历史中 `/api/pawn/context` 与 `/api/pawn/remember` 返回 200。
7. 账本 `ticket_count = 1` 的终端截图。

把实际 Dify 版本、模型 Provider/模型名、截图文件名和观察结果补到 `docs/VALIDATION.md`。截图和录屏是辅助证据，不能替代可运行的应用与复现步骤。

## 6. 打包与提交

先生成干净提交目录：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\package-submission.ps1
```

默认输出到：

```text
work/submission/memory-pawnshop/
```

脚本会排除 `.env`、`ledger.json`、`node_modules`、`__pycache__` 等运行时文件，并扫描常见密钥格式。检查 `SUBMISSION_MANIFEST.json` 后，把整个 `memory-pawnshop` 目录放入比赛私有仓库的 `dify/` 下：

```text
powercontext/
└─ dify/
   └─ memory-pawnshop/
```

提交前确认：

- 没有真实 API Key、密码或 Token。
- 没有 `backend/.env`、`data/ledger.json`、PowerContext 数据库。
- `README.md` 中的 Dify 版本、模型和地址与实际演示一致。
- 记录分支名和 commit hash，填入测评平台。

## 常见问题

| 现象 | 处理 |
| --- | --- |
| Docker CLI 不存在 | 安装并启动 Docker Desktop（作者环境已安装 29.9.2，WSL2 引擎）。 |
| WSL 未安装 | 管理员执行 `wsl --install`，重启后再启动 Docker Desktop。 |
| 磁盘不足 | 清理 Docker 镜像/卷，至少保留 20 GB；不要删除其他项目数据。 |
| Dify 导入后模型不可用 | 安装对应模型插件并重新绑定“掌柜阿当”节点。 |
| HTTP 节点连不上后端 | 先确认 `host.docker.internal:8765/health` 在 Dify 容器内可达，再检查 SSRF 白名单和 Windows 防火墙。 |
| 第二轮没有旧账 | 确认两次对话使用同一个“当票号：小满”，并检查第一轮 `remember` 是否返回 200。 |
| 第三轮新增了当票 | 确认消息被识别为 `redeem`；查看 `/api/pawn/ledger` 的 `ticket_count`。 |

