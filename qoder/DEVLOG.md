# 开发记录

日期：2026-10-27
开发者：Qoder Agent
环境：Windows 25H2, Python 3.13 (F:\python3.13.5)

## 环境核实

### 仓库状态
- 仓库: oceanbase/powercontext
- 分支: 2026-competition-ecosystem ✅
- 项目目录: qoder/
- Git 状态: 正确，已有用户修改（任务书等文件为 untracked）

### 运行环境
- Python: 3.13.16 (默认 python) / 3.13.7 (F:\python3.13.5)
- pip: 25.2
- 操作系统: Windows 25H2

### seekdb 连接状态
- **未配置**: 环境变量 SEEKDB_HOST/PORT/USER/PASSWORD/DATABASE 均为空
- **实际使用**: SQLite 本地开发模式
- **切换方式**: 设置 SEEKDB_HOST 后自动使用 seekdb (MySQL 协议)

### 依赖安装
已安装（F:\python3.13.5 环境）：
- fastapi==0.162.0
- uvicorn==0.54.0
- sqlalchemy==2.1.6
- pymysql==1.2.3
- python-multipart==0.0.32
- jinja2==3.1.6
- aiofiles==25.1.0
- httpx==0.28.1
- pytest==9.1.1
- pytest-asyncio==1.4.1

## 开发过程

### 1. 数据库 Schema 设计
- 创建 `documents` 表：id, title, doc_type, tags, content, source_file, paragraphs, created_at, updated_at
- 索引：title (index), doc_type (index), idx_type_tags (复合索引)
- 使用 SQLAlchemy ORM，支持 seekdb (MySQL协议) 和 SQLite 双模式

### 2. API 实现
- POST /api/documents/upload - 文件上传，自动解析元数据
- GET /api/documents/search - 关键词搜索 + 类型/标签筛选
- GET /api/documents/{id} - 获取详情
- DELETE /api/documents/{id} - 删除文档
- GET /api/documents/ - 列表全部
- GET /api/health - 健康检查

### 3. 前端实现
- 搜索框 + 类型下拉 + 标签输入
- 文件上传区域（拖拽 + 点击）
- 结果列表（匹配段落高亮）
- 详情弹窗
- 删除按钮

### 4. 安全措施
- 所有 SQL 参数化（SQLAlchemy ORM）
- LIKE 查询转义特殊字符（%, _, \）
- 前端 HTML 转义（textContent）
- 文件类型限制（.md, .txt）
- 文件大小限制（5MB）
- UTF-8 编码要求

### 5. 同名文件处理
- 检测已存在同名 source_file
- 自动添加后缀 _1, _2... 避免覆盖
- 每份文档独立 ID

## 测试记录

### 单元测试 (pytest)
```
15 passed in 7.97s
```

覆盖：
- 健康检查 ✅
- 文档上传 ✅
- 文件类型拒绝 ✅
- 同名文件不覆盖 ✅
- 关键词搜索 (ANC_NOTE_731, ANC_EXP_842, ANC_TODO_953) ✅
- shared_anchor 返回三份 ✅
- 类型筛选 ✅
- 标签筛选 ✅
- 无结果搜索 ✅
- SQL 注入安全 ✅
- 文档删除 ✅
- 删除影响搜索 ✅
- HTML 脚本安全 ✅

### 实时 API 验证 (verify_live.py)
```
16/16 PASS
```

### 中文查询测试
- "合成" -> 2 results (reading + todo) ✅
- "待办" + type=todo -> 1 result ✅
- 说明：使用 LIKE 子串匹配，未使用全文分词

## seekdb 作用证据

### 数据库写入
- 文档保存实际写入 SQLite/seekdb
- 示例：ID=1, title=合成实验记录, type=experiment, tags=baseline

### 参数化查询模板
```sql
SELECT * FROM documents 
WHERE (title LIKE ? OR content LIKE ? OR tags LIKE ?)
AND doc_type = ?
AND tags LIKE ?
```

### 删除由数据库状态决定
- 删除 ID=1 后，搜索 ANC_EXP_842 返回空
- 其他文档仍可检索（ID=2, ID=3）

## 历史未完成项（2026-10-27；以文末最新状态为准）

- [ ] seekdb 实际连接（需要配置环境变量）
- [ ] Qoder Sites 网站发布（需要人工操作）
- [ ] 真实用户数据/提效统计（首次版本不伪造）

## 历史人工步骤（以 README 最新启动方式为准）

1. **seekdb 连接**: 设置环境变量 SEEKDB_HOST, SEEKDB_PORT, SEEKDB_USER, SEEKDB_PASSWORD, SEEKDB_DATABASE
2. **网站发布**: 通过 Qoder Sites 发布公开展示网站
3. **提交材料**: 网站网址、代码仓库、运行说明、验证样例、Qoder 开发记录截图、账号 UID

## 2026-10-28 最新修复与验收（Codex）

本节覆盖上文历史 seekdb 未连接状态：已在真实 `5.7.25-OceanBase seekdb-v1.4.0.0`、独立库 `qoder_research` 完成验证。

- Qoder 当日增加 25 项测试和展示页；Codex 完成首页模板、URL.create、pool_pre_ping、统一临时 SQLite 隔离、安全元数据/标签处理及 3 项回归。
- 全量 pytest：43 passed；1 个 TestClient/httpx 弃用 warning。交付包保存重新运行日志；测试不对真实业务库清表。
- 2026-10-28 20:57:34 +08:00：19 项 Chromium/真实 seekdb 检查全过，含服务重启后持久化；测试资料已清理，原有资料保留。
- 增加统一启动与浏览器验收脚本；连接仅显式 JSON 或进程环境变量，不自动读取 .env，不交付真实凭据。
- 更新 README/展示页最新事实与开发归属。静态展示不等于在线 FastAPI 服务。
- 原生 Qoder Sites/UID 以 submission/PUBLISH_STATUS.md 及真实回执为准；GitHub/平台由队友完成，未虚构网址、仓库/commit、提测或得分。
