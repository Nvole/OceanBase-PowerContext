# OceanBase seekdb x Dify：离谱辩题

这是可复测的 Dify 主链路版本。提交时只复制本目录 dify/，不要把旧版 Dify 目录叠加保留。

## 已修复的退回原因

- 主入口是已导入、已发布的 Dify Workflow /v1/workflows/run，不是直接 curl 后端冒充 Dify。
- DSL 已包含 7 个真实节点：输入、序列化、seekdb 混合检索、规则主持、seekdb 写入、写入确认、结束。
- docs/absurd_debate.dsl.yml 是实际导入并运行过的 DSL；evidence/ 保存真实导入、发布、运行和节点执行轨迹。
- 后端依赖全部位于本目录，删除了仓库外 scripts/db.py 依赖。
- Dify、seekdb、插件守护进程和沙箱版本已固定；网络地址使用 Compose 内可解析的 http://debate:18604，不使用容器内 localhost。
- 提交前必须把本目录完整推送到目标分支，并使用真实的远端分支 HEAD 做匿名 fresh clone 校验。

## 运行边界

- 主链路使用 Dify 编排和 seekdb 检索/持久化。
- “主持”节点是确定性规则代码，不冒充大模型推理，不需要模型 API Key。
- Dify 元数据使用本地 PostgreSQL/Redis；业务文档和向量使用 OceanBase seekdb 专用数据库 dify_v2_debate。
- 默认仅绑定本机端口，不是公网部署方案。

## 提交前操作

### 1. 替换仓库中的旧目录

先备份自己未提交的修改，再删除目标仓库内旧的 dify/，将本目录完整复制为新的 dify/。不要只覆盖部分文件；提交内容应以本目录的 Dify 主链路说明、脚本和证据为准。

    git status --short
    git rm -r -- dify
    # 将本交付包中的 dify/ 复制到仓库根目录
    git add dify
    git diff --cached --stat
    git diff --cached -- dify/README.md dify/docs/absurd_debate.dsl.yml dify/compose.yaml

### 2. 准备本机配置

在 dify/ 目录执行。不要提交 .env、.runtime/、数据库连接文件或密码。

    python scripts/configure.py
    # 编辑 .env，填入 SEEKDB_HOST、SEEKDB_USER、SEEKDB_PASSWORD

### 3. 启动、导入、发布、验收

确保 Docker、Compose 和 seekdb 可用；在 Docker 容器能访问宿主 seekdb 的环境中执行：

    python scripts/start.py --initialize-local --seekdb-host 127.0.0.1

Windows + WSL Docker 示例：

    $env:DIFY_DOCKER_COMMAND='["wsl","-d","seekdb-ubuntu","--","docker"]'
    python scripts/start.py --initialize-local --seekdb-host 127.0.0.1

脚本会构建后端、初始化专用 seekdb、启动真实 Dify、导入并发布 DSL、通过 Dify /v1/workflows/run 执行 4 轮、检查 7 节点轨迹、验证连续记忆、幂等写入和后端重启后的持久化，并运行本地提交内容检查。

### 4. 推送后做远端检出检查

提交并推送后，记录目标分支的完整 40 位 SHA。不要把网页 /tree/ 或 /commit/ 地址当作仓库地址。

    git add dify
    git commit -m "fix: submit runnable Dify seekdb workflow"
    git push origin 2026-competition-ecosystem
    git rev-parse HEAD
    python dify/scripts/verify_submission.py --repository https://github.com/Nvole/OceanBase-PowerContext.git --branch 2026-competition-ecosystem --commit <刚刚推送的完整40位SHA> --output dify_remote_submission_check.json

只有看到 anonymous_remote_clone: true、passed: true，并且检查报告中的 SHA 与刚推送的分支 HEAD 一致，才把提交信息发给老师。若仓库权限导致匿名 clone 失败，先按比赛要求处理仓库可见性/授权，再重跑，不要用本地检查结果代替远端检查。

## 交付证据

- docs/absurd_debate.dsl.yml：已实际导入并发布过的 Workflow DSL。
- evidence/dify_import.json：真实 Dify 导入、发布和无密钥导出记录。
- evidence/dify_acceptance.json：真实 Workflow 运行、节点数、seekdb、重启持久化和源文件指纹。
- evidence/*_nodes.json：Dify 控制台返回的节点执行轨迹。
- evidence/pytest.txt：单元/发布检查结果。
- scripts/verify_submission.py：匿名 fresh clone、精确分支 HEAD、内容和证据链检查器。

## 端口

- Dify Web：127.0.0.1:13000
- Dify API：127.0.0.1:15001
- 业务后端：127.0.0.1:18604
- seekdb：按 .env 中的配置连接，默认端口 2881

本交付包已在本地真实 Dify 1.12.0 + OceanBase seekdb v1.4.0.0 环境验收通过；不能替代队友推送后的真实远端 clone 检查，也不承诺平台环境必然通过。
